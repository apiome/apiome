# Enum Sorting Feature

## Overview
The property form now includes the ability to sort enumeration values in ascending (A-Z) or descending (Z-A) order.

## Implementation Details

### Location
The sorting functionality is implemented in:
- `src/app/components/ade/studio/PropertyFormFields.tsx`

### Features

#### Sort Buttons
- **A-Z Button**: Sorts enum values in ascending order
  - For strings: Alphabetical order (case-insensitive)
  - For numbers/integers: Numeric order (lowest to highest)
  
- **Z-A Button**: Sorts enum values in descending order
  - For strings: Reverse alphabetical order (case-insensitive)
  - For numbers/integers: Reverse numeric order (highest to lowest)

#### Visual Design
- Sort buttons only appear when there are 2 or more enum values
- Buttons are displayed in the header of the "Allowed Values (Enum)" section
- Buttons feature:
  - Border styling for visibility
  - Tooltips explaining the sort direction
  - The Z-A button uses a flipped icon (transform: scaleY(-1))
  - Small, compact design to save space

### Usage

1. Add at least 2 enum values to a property
2. The sort buttons will automatically appear in the enum section header
3. Click the A-Z button to sort in ascending order
4. Click the Z-A button (flipped icon) to sort in descending order

### Code Example

```typescript
const handleSortEnumAZ = () => {
  if (!data.enum || data.enum.length === 0) return;
  
  const sorted = [...data.enum].sort((a, b) => {
    // For numeric types, sort as numbers
    if (baseType === 'number' || baseType === 'integer') {
      return Number(a) - Number(b);
    }
    // For strings, sort alphabetically (case-insensitive)
    return a.toLowerCase().localeCompare(b.toLowerCase());
  });
  
  onChange('enum', sorted);
};

const handleSortEnumZA = () => {
  if (!data.enum || data.enum.length === 0) return;
  
  const sorted = [...data.enum].sort((a, b) => {
    // For numeric types, sort as numbers in descending order
    if (baseType === 'number' || baseType === 'integer') {
      return Number(b) - Number(a);
    }
    // For strings, sort alphabetically in reverse (case-insensitive)
    return b.toLowerCase().localeCompare(a.toLowerCase());
  });
  
  onChange('enum', sorted);
};
```

### Supported Types
- String enumerations
- Number enumerations
- Integer enumerations

### Future Enhancements
- Manual drag-and-drop reordering of enum values (planned)
- Custom sort options (e.g., by creation order)
- Undo/redo functionality for enum changes

## Testing

To test the sorting feature:

1. Navigate to the Studio view
2. Create or edit a property with type: string, number, or integer
3. Add multiple enum values (e.g., "zebra", "apple", "banana")
4. Click the A-Z button to see them sorted: "apple", "banana", "zebra"
5. Click the Z-A button to see them sorted in reverse: "zebra", "banana", "apple"

For numeric enums:
1. Create a property with type: number or integer
2. Add values: 100, 5, 42, 3
3. Click A-Z to sort: 3, 5, 42, 100
4. Click Z-A to sort: 100, 42, 5, 3

## Technical Notes

- The sort is case-insensitive for string values
- Numeric sorting properly handles decimal numbers
- The original enum array is not mutated (uses spread operator)
- Empty or single-item enum lists don't show sort buttons
- Sort buttons are conditionally rendered for better UX

