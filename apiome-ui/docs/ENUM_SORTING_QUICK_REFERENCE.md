# Enum Sorting Feature - Quick Reference

## Visual Layout

When editing a property with enum values, the sorting buttons appear in the header:

```
┌─────────────────────────────────────────────────────┐
│ Allowed Values (Enum)          [A→Z] [Z→A]          │
├─────────────────────────────────────────────────────┤
│                                                     │
│ Add Enum Value: [____________] [+]                  │
│ Enter a string value and press Enter                │
│                                                     │
│ ┌─────────────────────────────────────────────┐    │
│ │ apple                                    [×]│    │
│ ├─────────────────────────────────────────────┤    │
│ │ banana                                   [×]│    │
│ ├─────────────────────────────────────────────┤    │
│ │ zebra                                    [×]│    │
│ └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

## Button Behavior

### A-Z Button (Ascending Sort)
- **Icon**: `SortByAlphaIcon` (upright)
- **Tooltip**: "Sort A-Z (ascending)"
- **Strings**: apple → banana → cherry
- **Numbers**: 1 → 5 → 42 → 100
- **Case-insensitive**: "Apple" and "apple" treated the same

### Z-A Button (Descending Sort)
- **Icon**: `SortByAlphaIcon` (flipped vertically)
- **Tooltip**: "Sort Z-A (descending)"
- **Strings**: zebra → banana → apple
- **Numbers**: 100 → 42 → 5 → 1
- **Case-insensitive**: "Zebra" and "zebra" treated the same

## Button States

| Condition | Button Visibility |
|-----------|------------------|
| 0 enum values | Hidden |
| 1 enum value | Hidden |
| 2+ enum values | Visible |

## Examples

### Example 1: String Enum (Unsorted)
**Before sorting:**
- `"Pending"`
- `"active"`
- `"Completed"`
- `"cancelled"`

**After A-Z:**
- `"active"`
- `"cancelled"`
- `"Completed"`
- `"Pending"`

**After Z-A:**
- `"Pending"`
- `"Completed"`
- `"cancelled"`
- `"active"`

### Example 2: Integer Enum (Unsorted)
**Before sorting:**
- `100`
- `5`
- `42`
- `3`

**After A-Z:**
- `3`
- `5`
- `42`
- `100`

**After Z-A:**
- `100`
- `42`
- `5`
- `3`

### Example 3: Number Enum with Decimals
**Before sorting:**
- `3.14`
- `2.71`
- `1.41`
- `9.81`

**After A-Z:**
- `1.41`
- `2.71`
- `3.14`
- `9.81`

**After Z-A:**
- `9.81`
- `3.14`
- `2.71`
- `1.41`

## UI Components Used

- **Button Container**: MUI `Box` with flex layout
- **Buttons**: MUI `IconButton` with border styling
- **Icon**: MUI `SortByAlphaIcon`
- **Tooltips**: MUI `Tooltip` for user guidance
- **Styling**: Consistent with existing form design

## Accessibility

- ✅ Tooltips provide clear descriptions
- ✅ Buttons have clear visual boundaries (bordered)
- ✅ Icon flip (scaleY) provides visual distinction between A-Z and Z-A
- ✅ Buttons are properly sized for touch targets
- ✅ Conditional rendering prevents clutter when not needed

## Implementation Notes

1. **Non-mutating**: Original array is not modified (uses spread operator)
2. **Type-aware**: Different sorting logic for strings vs. numbers
3. **Case-insensitive**: String comparisons ignore case
4. **Performant**: Only shows buttons when needed (2+ items)
5. **Integrated**: Matches existing design patterns in PropertyFormFields

