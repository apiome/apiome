# Edge Styling Feature

## Overview

Added the ability to change line styling for edges in the canvas editor, allowing users to customize how different types of relationships are visually represented.

## Edge Style Types

The following edge style types are now available:

1. **Solid** - Continuous line (default for direct references)
2. **Dashed** - Medium dashes (default for optional references)
3. **Dotted** - Small dots with gaps (default for weak references)
4. **Double** - Thicker lines representing double lines (default for bi-directional)

## Edge Categories

Edges are automatically categorized into four types:

1. **Direct References** - Standard property references between classes
2. **Optional References** - Composition types like `anyOf` and `oneOf`
3. **Weak References** - Composition types like `allOf`
4. **Bidirectional** - Edges with both start and end markers

## Implementation Details

### Files Created

1. **`/src/app/utils/edge-styling.ts`**
   - `getStrokeDashArray()` - Converts style type to SVG dash array
   - `getEdgeStrokeStyle()` - Returns stroke style properties
   - `categorizeEdge()` - Determines edge category
   - `applyEdgeStyling()` - Applies styling based on preferences

2. **`/tests/edge-styling.test.ts`**
   - Comprehensive test suite with 22 tests
   - Tests all utility functions and edge cases

### Files Modified

1. **`/src/app/ade/studio/StudioContext.tsx`**
   - Added `EdgeStyleType` type
   - Added `EdgeStylingOptions` interface
   - Added `edgeStyling` state with localStorage persistence
   - Default settings:
     - Direct: solid
     - Optional: dashed
     - Weak: dotted
     - Bidirectional: double

2. **`/src/app/ade/studio/components/StudioHeader.tsx`**
   - Added edge styling controls to Settings dropdown
   - Four dropdowns (Direct, Optional, Weak, Bidirectional)
   - Each allows selection of: Solid, Dashed, Dotted, or Double

3. **`/src/app/ade/studio/editor/page.tsx`**
   - Imported `applyEdgeStyling` utility
   - Added `edgeStyling` to context
   - Modified `createPropertyRefEdges()` to apply styling
   - Modified `createCompositionEdges()` to apply styling
   - Added `useEffect` to regenerate edges when styling changes

## User Interface

### Accessing Edge Styling

1. Click the **Settings** button (gear icon) in the Studio Header
2. Scroll down to the **Edge Styles** section
3. Configure each edge category:
   - **Direct** - For standard property references
   - **Optional** - For anyOf/oneOf composition
   - **Weak** - For allOf composition
   - **Bidirectional** - For two-way relationships

### Settings Persistence

- Edge styling preferences are saved to browser localStorage
- Settings persist across sessions
- Settings are applied immediately to all edges on the canvas

## Visual Examples

### Solid Lines
- Continuous unbroken line
- Default for direct property references
- Clear indication of primary relationships

### Dashed Lines
- Medium-length dashes with gaps (5,5 pattern)
- Default for optional relationships (anyOf/oneOf)
- Indicates alternative choices

### Dotted Lines
- Small dots with gaps (2,3 pattern)
- Default for weak relationships (allOf)
- Indicates composition/inheritance

### Double Lines
- Thicker stroke (2.5x original width)
- Default for bidirectional relationships
- Emphasizes two-way connections

## Technical Details

### Stroke Patterns

- **Solid**: No strokeDasharray
- **Dashed**: strokeDasharray: "5,5"
- **Dotted**: strokeDasharray: "2,3"
- **Double**: strokeWidth multiplied by 2.5

### Edge Categorization Logic

```typescript
- Bidirectional: Has both markerStart and markerEnd
- Optional: Label contains "anyof" or "oneof"
- Weak: Label contains "allof"
- Direct: All other edges (default)
```

### Color Preservation

The styling utility preserves:
- Original edge colors
- Original stroke widths (except for double style)
- All other edge properties (animated, type, labels, etc.)

## Testing

All 22 tests pass:
- Style type conversion (4 tests)
- Stroke style generation (4 tests)
- Edge categorization (6 tests)
- Style application (6 tests)
- Integration scenarios (2 tests)

## Future Enhancements

Potential improvements for future iterations:

1. **Custom Patterns** - Allow users to define custom dash patterns
2. **Pattern Preview** - Show visual preview of each style in settings
3. **Edge Color Customization** - Allow color changes per category
4. **Export/Import Settings** - Save/load styling preferences
5. **Presets** - Predefined styling themes (e.g., UML, ERD)
6. **Animation Options** - Different animation styles per category

