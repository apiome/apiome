# Edge Cardinality Visualization

## Overview

Edges (connections) between classes now visually represent the cardinality of relationships based on whether properties are arrays or single references. This makes it immediately clear whether a relationship is one-to-one, one-to-many, many-to-one, or many-to-many.

## Visual Legend

### Marker Types

- **Closed Arrow (►)**: Represents "one" side of a relationship
- **Open Arrow (⊳)**: Represents "many" side of a relationship

### Colors & Cardinality

| Relationship | Color | Source Marker | Target Marker | Label |
|--------------|-------|---------------|---------------|-------|
| **One-to-One** | Blue (#3b82f6) | ► (if bidirectional) | ► | `propertyName (1:1)` or `(1)` |
| **One-to-Many** | Purple (#8b5cf6) | ► (if bidirectional) | ⊳ | `propertyName (1:N)` |
| **Many-to-One** | Amber (#f59e0b) | ⊳ | ► | `propertyName (N:1)` |
| **Many-to-Many** | Pink (#ec4899) | ⊳ | ⊳ | `propertyName (N:N)` |

## How It Works

### Detection Logic

The edge creation algorithm examines both the source and target properties:

1. **Source Property Analysis**:
   - Check if property is an array: `{ "type": "array", "items": { "$ref": "..." } }`
   - If array → "many" on source side
   - If not array → "one" on source side

2. **Target Property Analysis**:
   - Search target class for a property referencing back to source class
   - If found and is array → "many" on target side
   - If found and not array → "one" on target side
   - If not found → unidirectional relationship

3. **Cardinality Determination**:
   ```
   Source Array? | Target Array? | Bidirectional? | Result
   --------------|---------------|----------------|-------------
   No            | No            | Yes            | One-to-One (1:1)
   No            | No            | No             | One (1)
   No            | Yes           | Yes            | Many-to-One (N:1)
   Yes           | No            | Yes            | One-to-Many (1:N)
   Yes           | Yes           | Yes            | Many-to-Many (N:N)
   Yes           | -             | No             | Many-to-One (N:1)
   ```

## Examples

### Example 1: One-to-One (User ↔ Profile)

**User class:**
```json
{
  "properties": {
    "profile": {
      "$ref": "#/components/schemas/Profile"
    }
  }
}
```

**Profile class:**
```json
{
  "properties": {
    "user": {
      "$ref": "#/components/schemas/User"
    }
  }
}
```

**Result**: Blue edge with closed arrows on both ends, labeled `profile (1:1)`

### Example 2: One-to-Many (User → Posts)

**User class:**
```json
{
  "properties": {
    "posts": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Post"
      }
    }
  }
}
```

**Post class:**
```json
{
  "properties": {
    "author": {
      "$ref": "#/components/schemas/User"
    }
  }
}
```

**Result**: Purple edge with closed arrow at User (source) and open arrow at Post (target), labeled `posts (1:N)`

### Example 3: Many-to-Many (Student ↔ Course)

**Student class:**
```json
{
  "properties": {
    "courses": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Course"
      }
    }
  }
}
```

**Course class:**
```json
{
  "properties": {
    "students": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Student"
      }
    }
  }
}
```

**Result**: Pink edge with open arrows on both ends, labeled `courses (N:N)`

### Example 4: Unidirectional One-to-Many (Order → LineItems)

**Order class:**
```json
{
  "properties": {
    "lineItems": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/LineItem"
      }
    }
  }
}
```

**LineItem class:**
```json
{
  "properties": {
    // No reference back to Order
  }
}
```

**Result**: Purple edge with no source marker and open arrow at LineItem, labeled `lineItems (N:1)`

## Implementation Details

### File Modified
`/objectified-ui/src/app/ade/studio/page.tsx`

### Function Updated
`createPropertyRefEdges(classes: any[]): Edge[]`

### Key Changes

1. **Bidirectional Detection**:
   ```typescript
   // Check if target class has a reference back to this class
   let isTargetArray = false;
   let hasReverseRef = false;
   
   if (targetClass && targetClass.properties) {
     const sourceClassName = cls.name;
     targetClass.properties.forEach((targetProp: any) => {
       const targetPropData = ...;
       const targetRefName = ...;
       
       if (targetRefName === sourceClassName) {
         hasReverseRef = true;
         isTargetArray = targetPropData.type === 'array';
       }
     });
   }
   ```

2. **Marker Configuration**:
   ```typescript
   if (isSourceArray && isTargetArray) {
     // Many-to-Many
     markerStart = { type: 'arrow', ... };
     markerEnd = { type: 'arrow', ... };
   } else if (isSourceArray && !isTargetArray) {
     // One-to-Many
     markerStart = hasReverseRef ? { type: 'arrowclosed', ... } : undefined;
     markerEnd = { type: 'arrow', ... };
   }
   // ... etc
   ```

3. **Label Enhancement**:
   ```typescript
   label: `${prop.name} (${cardinality})`
   ```

## Benefits

### For Developers
- **Quick Understanding**: Instantly see relationship types without inspecting properties
- **Schema Validation**: Visually verify that cardinality matches intended design
- **Debugging**: Identify incorrect relationship configurations

### For Database Design
- **ER Diagram Equivalent**: Canvas now functions as an Entity-Relationship diagram
- **Normalization Review**: Spot many-to-many relationships that may need junction tables
- **Foreign Key Planning**: Understand which side should hold the foreign key

### For API Design
- **Endpoint Planning**: Know which resources should have nested arrays
- **Join Strategy**: Identify where to implement joins or includes
- **Performance**: Spot N+1 query risks in one-to-many relationships

## Edge Cases Handled

### Circular References
```json
User → Department (1:1)
Department → User (1:1)
```
Both edges are created and properly styled, showing bidirectional one-to-one relationships.

### Self-References
```json
Employee → Employee (manager)
```
Handled correctly as one-to-one or one-to-many depending on array type.

### Multiple References Between Classes
```json
User → Post (author, array)
User → Post (editor, single)
```
Each property creates its own edge with appropriate cardinality.

### Dangling References
```json
Post → User (author, deleted User class)
```
No edge created (target class not found in classNameToId map).

## Future Enhancements

### Potential Additions
1. **Crow's Foot Notation**: Alternative marker style matching traditional ER diagrams
2. **Cardinality Constraints**: Show min/max on edges (e.g., "1..* → 0..1")
3. **Edge Filtering**: Toggle to show/hide certain cardinality types
4. **Color Customization**: User-configurable color scheme for relationships
5. **Junction Table Detection**: Identify and visualize many-to-many through join tables

### Configuration Options
Future config dialog could include:
- Marker style preference (arrow vs crow's foot)
- Show/hide cardinality labels
- Color theme selection
- Edge animation for specific cardinalities

## Testing Checklist

- [x] One-to-one bidirectional shows blue with closed arrows both ends
- [x] One-to-one unidirectional shows blue with closed arrow at target only
- [x] One-to-many shows purple with closed arrow at source, open at target
- [x] Many-to-one shows amber with open arrow at source, closed at target
- [x] Many-to-many shows pink with open arrows both ends
- [x] Labels include cardinality notation (1, 1:1, 1:N, N:1, N:N)
- [x] Colors are distinct and accessible
- [x] Multiple edges between same classes work correctly
- [x] Self-references render properly

## Related Documentation

- `REFERENCE_DRAG_DROP_IMPLEMENTATION.md` - Reference creation workflow
- `FIX_REFERENCE_HANDLE_VISIBILITY.md` - Handle visibility rules
- `OPENAPI_IMPORT_REFERENCE_HANDLING.md` - Import behavior

## Date
November 14, 2025

## Status
✅ **IMPLEMENTED** - Edges now visually represent relationship cardinality

