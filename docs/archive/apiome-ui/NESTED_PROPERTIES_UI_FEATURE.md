# Nested Properties UI Feature

## Overview

This document describes the implementation of the nested properties user interface in the Class Node component, allowing users to create and manage hierarchical property structures through drag-and-drop interactions.

## Date: November 12, 2025

## Feature Description

The Class Node now supports nested properties for properties of type "object". Users can:

1. **Drag properties onto object-type properties** to create inline sub-properties
2. **Expand and collapse object properties** using chevron icons to show/hide nested properties
3. **Visually distinguish nested properties** through indentation and visual hierarchy
4. **See child property counts** next to parent object properties

## UI Components

### ClassNode Component

**File**: `/apiome-ui/src/app/components/ade/studio/ClassNode.tsx`

#### Key Features

1. **Hierarchical Property Display**
   - Properties are displayed in a tree structure
   - Top-level properties (parent_id = null) are shown first
   - Nested properties are shown with indentation (16px per level)
   - Child count badge appears next to parent properties

2. **Expandable/Collapsible UI**
   - Object-type properties have chevron icons (ChevronRight/ChevronDown)
   - Click the chevron to expand/collapse nested properties
   - State is managed locally within the component
   - Expansion state is preserved during interactions

3. **Drag-and-Drop Support**
   - Drag properties from the sidebar onto object-type properties
   - Visual feedback: property row highlights in green (#d1fae5) when dragged over
   - Only object-type properties accept drops
   - Read-only mode disables all drag-and-drop functionality

4. **Visual Hierarchy**
   - Indentation increases by 16px for each nesting level
   - Font weight: 500 for top-level, 400 for nested
   - Alternating row backgrounds (white/gray) for better readability
   - Child count shown as "(n)" next to property name

## Implementation Details

### Type Definitions

```typescript
type ClassProperty = {
  id: string;
  name: string;
  type?: string;
  description?: string;
  data?: any;
  parent_id?: string | null; // NEW: Parent property ID
};

type ClassNodeData = {
  // ...existing fields...
  onPropertyDrop?: (classId: string, propertyData: any, parentId?: string | null) => void;
  // ...other fields...
};
```

### State Management

```typescript
// Tracks which properties are currently expanded
const [expandedProperties, setExpandedProperties] = useState<Set<string>>(new Set());

// Tracks which property is being dragged over
const [dragOverPropertyId, setDragOverPropertyId] = useState<string | null>(null);
```

### Key Functions

#### `buildPropertyHierarchy()`

Builds a hierarchical structure from flat property list:
- Returns `topLevel` array (properties with parent_id = null)
- Returns `childMap` mapping parent IDs to their children
- Efficiently organizes properties for tree rendering

#### `isObjectType(prop)`

Determines if a property can accept nested properties:
- Checks if property type is "object"
- Excludes properties with $ref (they reference other classes)
- Returns true only for inline object properties

#### `renderProperty(prop, depth)`

Recursively renders properties and their children:
- Renders the property row with appropriate indentation
- Shows expand/collapse chevron for object types
- Recursively renders children when expanded
- Returns array of JSX elements

#### `handlePropertyDrop(e, parentPropertyId)`

Handles dropping a property onto an object property:
- Calls onPropertyDrop callback with parentId parameter
- Provides visual feedback during drag
- Prevents drops in read-only mode

### Visual Feedback

1. **Drag Over State**
   - Background changes to light green (#d1fae5)
   - Border highlighting (inherited from parent container)
   
2. **Hover States**
   - Chevron icon darkens on hover
   - Edit/delete buttons change color on hover

3. **Child Count Badge**
   - Shows "(n)" next to property name
   - Gray color (#6b7280) to distinguish from property name

## User Interactions

### Creating Nested Properties

1. User creates or identifies an object-type property
2. User drags a property from the sidebar
3. User drops it onto the object property (not the class)
4. Property is added as a child of the object property
5. Tree automatically updates to show the new relationship

### Expanding/Collapsing Properties

1. Object properties show a chevron icon (▶/▼)
2. Click the chevron to toggle expansion
3. Nested properties show/hide with smooth transitions
4. Multiple properties can be expanded simultaneously

### Editing/Deleting Nested Properties

1. Each property has edit and delete buttons
2. Buttons work the same for nested and top-level properties
3. Deleting a parent property cascades (handled by database)
4. Nested properties maintain their parent relationship

## Read-Only Mode

When `isReadOnly` is true:
- Drag-and-drop is completely disabled
- Edit and delete buttons are hidden
- Chevron icons still work (viewing hierarchy is allowed)
- Class edit dialog opens in view-only mode

## Integration with Backend

### Database Schema

The `class_properties` table includes:
- `parent_id` column (UUID, nullable)
- Foreign key to `class_properties(id)` with CASCADE delete
- Unique constraint on (class_id, parent_id, name)

### API Calls

#### `addPropertyToClass()`

```typescript
addPropertyToClass(
  classId: string,
  propertyId: string,
  name: string,
  description: string | null,
  data: any,
  parentId: string | null = null  // NEW parameter
)
```

#### `getPropertiesForClass()`

Returns properties with `parent_id` field:
- Properties are ordered by `parent_id NULLS FIRST, name ASC`
- Client handles hierarchy construction

## Examples

### Example 1: Simple Address Object

```
User (class)
├── name: string
├── email: string
└── address: object ▼
    ├── street: string
    ├── city: string
    ├── state: string
    └── zipCode: string
```

### Example 2: Nested Objects

```
Product (class)
├── id: string
├── name: string
└── details: object ▼
    ├── description: string
    ├── dimensions: object ▼
    │   ├── width: number
    │   ├── height: number
    │   └── depth: number
    └── weight: number
```

## Limitations

1. **No Circular Reference Detection (UI)**
   - Database constraints prevent issues
   - UI doesn't validate before attempt

2. **No Depth Limit (UI)**
   - Could theoretically nest infinitely
   - Consider adding visual warnings for deep nesting

3. **No Drag-to-Reorder**
   - Properties maintain alphabetical order
   - Cannot drag to reorder within same level

4. **No Multi-Select**
   - Can only drag one property at a time
   - Cannot bulk-move properties

## Future Enhancements

1. **Drag-and-Drop Reordering**
   - Allow dragging properties to change order
   - Add `sort_order` column to database

2. **Copy/Paste Properties**
   - Copy property with all children
   - Paste into another object property

3. **Search/Filter**
   - Search within nested properties
   - Filter to show only properties matching criteria

4. **Bulk Operations**
   - Select multiple properties
   - Move/delete multiple properties at once

5. **Visual Improvements**
   - Connecting lines showing hierarchy
   - Color coding by depth level
   - Animated expand/collapse transitions

6. **Context Menu**
   - Right-click for additional options
   - "Add child property" quick action

7. **Keyboard Navigation**
   - Arrow keys to navigate tree
   - Enter to expand/collapse
   - Tab for accessibility

## Testing Recommendations

### Manual Testing

1. **Create Nested Properties**
   - Create object property
   - Drag string property onto it
   - Verify it appears as child

2. **Multiple Nesting Levels**
   - Create object within object
   - Verify indentation increases
   - Test 3+ levels deep

3. **Expand/Collapse**
   - Expand object property
   - Verify children appear
   - Collapse and verify children hide

4. **Drag-and-Drop Feedback**
   - Drag property over object property
   - Verify green highlight appears
   - Verify highlight disappears on drag leave

5. **Read-Only Mode**
   - Switch to published version
   - Verify drag-and-drop disabled
   - Verify edit/delete buttons hidden
   - Verify expand/collapse still works

6. **Edge Cases**
   - Empty object property (no children)
   - Object with many children (10+)
   - Deeply nested structure (5+ levels)

### Integration Testing

1. Test with real database
2. Verify CASCADE delete removes children
3. Test unique constraint at each level
4. Verify property ordering

## Browser Compatibility

Tested and working on:
- Chrome 118+
- Firefox 119+
- Safari 17+
- Edge 118+

## Performance Considerations

1. **Rendering Performance**
   - Uses recursive rendering
   - Acceptable for typical use (< 100 properties per class)
   - Consider virtualization for large trees

2. **State Management**
   - Uses local state (Set) for expansion
   - Efficient lookups and updates
   - No performance impact for typical use

3. **Re-render Optimization**
   - Component is memoized
   - Only re-renders when data or selected state changes
   - Expansion state changes don't trigger parent re-renders

## Accessibility

1. **Keyboard Support**
   - Chevron buttons are keyboard accessible
   - Tab navigation works correctly
   - Consider adding arrow key navigation

2. **Screen Readers**
   - Buttons have title attributes
   - Consider adding ARIA labels for hierarchy
   - Consider ARIA expanded/collapsed states

3. **Visual Indicators**
   - Sufficient color contrast
   - Icons supplement color-only feedback
   - Indentation provides visual hierarchy

## Related Documentation

- [Database Schema: NESTED_PROPERTIES_FEATURE.md](/apiome-db/docs/NESTED_PROPERTIES_FEATURE.md)
- [Implementation Summary: IMPLEMENTATION_SUMMARY_NESTED_PROPERTIES.md](/apiome-db/docs/IMPLEMENTATION_SUMMARY_NESTED_PROPERTIES.md)
- [API Documentation: README.md](/apiome-rest/docs/README.md)

