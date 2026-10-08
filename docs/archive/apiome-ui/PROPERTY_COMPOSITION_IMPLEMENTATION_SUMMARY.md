# Property Multiple References Implementation Summary

## Date: November 22, 2025

## Overview
Successfully implemented the ability for properties to reference multiple classes using JSON Schema composition keywords (`allOf`, `anyOf`, `oneOf`), similar to how ClassNode implements composition.

## Changes Made

### 1. ReferenceDialog.tsx
**File:** `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/ReferenceDialog.tsx`

**Updates:**
- Added imports for Radio, RadioGroup, and Chip components
- Added new type: `CompositionType = 'none' | 'allOf' | 'anyOf' | 'oneOf'`
- Extended `ReferenceDialogProps` interface to include:
  - `targetClassIds?: string[]` - Array of class IDs for composition
  - `compositionType?: CompositionType` - The composition type
- Added state variables:
  - `compositionType` - Tracks selected composition type
  - `targetClassIds` - Stores multiple selected classes
- Enhanced UI with:
  - Radio group for selecting reference type (single vs composition)
  - Multiple class selection dropdown for composition modes
  - Visual chips showing selected classes
  - Contextual help text for each composition type
- Updated `handleSubmit` to validate and pass composition data

**Key Features:**
- Visual distinction between single reference and composition modes
- Multiple class selection with chip display
- Validation: At least one class required for composition types
- Help text explains each composition type's purpose

### 2. ClassNode.tsx
**File:** `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/ClassNode.tsx`

**Updates:**
- Enhanced `getPropertyType()` function to display composition types:
  - Direct composition: `allOf(User, Admin)`
  - Union: `anyOf(Email | Phone)`
  - Exclusive: `oneOf(Credit | Debit)`
  - Array composition: `allOf(User, Admin)[]`
- Updated `hasRef()` function to recognize:
  - Direct composition properties (`allOf`, `anyOf`, `oneOf`)
  - Composition in array items
- Improved type display for array items with composition

**Display Examples:**
```
allOf(User, Admin)        - Direct composition
anyOf(Email | Phone)[]    - Array of union
oneOf(A | B | C)          - Exclusive choice
```

### 3. studio/page.tsx
**File:** `/Users/kenji/Development/apiome/apiome-ui/src/app/ade/studio/page.tsx`

**Updates:**
- Updated `handleReferenceSubmit` callback signature to accept:
  - `targetClassIds?: string[]`
  - `compositionType?: string`
- Enhanced reference data building logic:
  - Handles composition types at property level
  - Handles composition types in array items
  - Builds proper JSON Schema structure
- Completely rewrote `createPropertyRefEdges()` function:
  - Added helper function `createCompositionEdges()`
  - Creates multiple edges for composition properties
  - Each reference gets its own styled edge
  - Proper edge styling based on composition type:
    - **allOf**: Blue (#2563eb), solid line
    - **anyOf**: Orange (#ea580c), dashed line (5,5)
    - **oneOf**: Purple (#9333ea), dotted line (2,3)
  - Labels show property name and composition type
  - Z-index layering for multiple edges
- Maintains backward compatibility with single $ref properties

**Edge Creation Logic:**
```typescript
// Checks for composition at property level
if (propData.allOf) createCompositionEdges('allOf', propData.allOf);
if (propData.anyOf) createCompositionEdges('anyOf', propData.anyOf);
if (propData.oneOf) createCompositionEdges('oneOf', propData.oneOf);

// Checks for composition in array items
if (propData.items?.allOf) createCompositionEdges('allOf', propData.items.allOf);
// ... etc
```

## Generated Schema Examples

### Single Reference (Existing)
```json
{
  "owner": {
    "$ref": "#/components/schemas/User"
  }
}
```

### allOf (Composition)
```json
{
  "admin": {
    "allOf": [
      { "$ref": "#/components/schemas/User" },
      { "$ref": "#/components/schemas/Administrator" }
    ]
  }
}
```

### anyOf (Union)
```json
{
  "contact": {
    "anyOf": [
      { "$ref": "#/components/schemas/Email" },
      { "$ref": "#/components/schemas/Phone" }
    ]
  }
}
```

### oneOf (Exclusive)
```json
{
  "payment": {
    "oneOf": [
      { "$ref": "#/components/schemas/CreditCard" },
      { "$ref": "#/components/schemas/Cash" }
    ]
  }
}
```

### Array with Composition
```json
{
  "contacts": {
    "type": "array",
    "minItems": 1,
    "items": {
      "anyOf": [
        { "$ref": "#/components/schemas/Email" },
        { "$ref": "#/components/schemas/Phone" }
      ]
    }
  }
}
```

## User Workflow

### Creating a Composition Reference

1. **Open Reference Dialog**
   - Drag "Reference" from sidebar OR
   - Click "Create Reference" button on class

2. **Configure Property**
   - Enter property name (e.g., "userAdmin")
   - Add description (optional)
   - Check "Array of references" if needed

3. **Select Composition Type**
   - Choose one of:
     - Single Reference (default, existing behavior)
     - allOf (must satisfy all)
     - anyOf (can satisfy any)
     - oneOf (must satisfy exactly one)

4. **Select Classes** (for composition types)
   - Use dropdown to add classes
   - Multiple classes shown as chips
   - Remove classes by clicking X on chip
   - Must select at least one class

5. **Submit**
   - Creates property with composition references
   - Multiple edges appear on canvas
   - Type displayed in property list

### Visual Indicators

**Canvas Edges:**
- Blue solid lines = allOf (inheritance/composition)
- Orange dashed lines = anyOf (union/alternatives)
- Purple dotted lines = oneOf (exclusive choice)

**Property Display:**
- Type shows composition: `allOf(User, Admin)`
- Array notation: `anyOf(Email | Phone)[]`
- Handle appears for reference connections

## Technical Details

### Composition Semantics

**allOf** - Must satisfy ALL referenced schemas
- Use for: Inheritance, mixins, required composition
- Example: Admin must be both User AND Administrator

**anyOf** - Must satisfy AT LEAST ONE referenced schema
- Use for: Unions, alternative representations
- Example: Contact can be Email OR Phone (or both)

**oneOf** - Must satisfy EXACTLY ONE referenced schema
- Use for: Discriminated unions, exclusive choices
- Example: Payment must be CreditCard OR Cash (not both)

### Data Flow

1. User selects composition type and classes in ReferenceDialog
2. Dialog passes composition data to `handleReferenceSubmit`
3. Studio page builds proper JSON Schema structure
4. Property saved to database with composition data
5. Canvas reload creates multiple edges
6. ClassNode displays formatted type string

### Edge Rendering

Each reference in a composition creates a separate edge:
- Source: Parent class
- Source Handle: `prop-{propertyId}`
- Target: Referenced class
- Styling: Based on composition type
- Label: Shows property name and composition type
- Z-index: Layered to prevent overlap

## Testing

### Build Status
✅ TypeScript compilation successful
✅ Next.js build successful
✅ No runtime errors

### Manual Testing Recommended
- [ ] Create property with allOf + 2 classes
- [ ] Create property with anyOf + 3 classes
- [ ] Create property with oneOf + 2 classes
- [ ] Create array with allOf in items
- [ ] Verify edges display with correct colors/styles
- [ ] Verify property type labels are correct
- [ ] Test with published (read-only) version
- [ ] Export and validate OpenAPI spec

## Files Modified
1. `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/ReferenceDialog.tsx`
2. `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/ClassNode.tsx`
3. `/Users/kenji/Development/apiome/apiome-ui/src/app/ade/studio/page.tsx`

## Documentation Created
- `/Users/kenji/Development/apiome/apiome-ui/docs/PROPERTY_COMPOSITION_REFERENCES.md`
- `/Users/kenji/Development/apiome/apiome-ui/docs/PROPERTY_COMPOSITION_IMPLEMENTATION_SUMMARY.md` (this file)

## Backward Compatibility
✅ Existing single reference properties work unchanged
✅ Existing array references work unchanged
✅ No breaking changes to database schema
✅ No breaking changes to API contracts

## Future Enhancements
1. Canvas-based editing: Add/remove references via drag-drop
2. Convert single reference to composition via context menu
3. Visual preview of composition validation
4. Import existing schemas with composition
5. Suggest composition types based on patterns

## Related Features
- Class composition (allOf/anyOf/oneOf at class level)
- Property references (single $ref)
- Nested properties (inline object structures)
- Array constraints (min/max items, uniqueItems)

## Notes
- Composition keywords follow JSON Schema specification
- Edge styling mirrors class-level composition conventions
- Multiple edges from same property use z-index layering
- Property type display is informative and compact
- Validation ensures at least one class for composition

