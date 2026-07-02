# Enumeration Value Reordering - User Guide

## Overview

The enumeration value reordering feature allows you to drag and drop enum values to arrange them in your preferred order within the property form.

## Features

### 1. **Drag Handle**
- Located on the **left side** of each enum value
- Visual indicator: Three horizontal lines (≡)
- Cursor changes to grab icon when hovering over it

### 2. **Drag to Reorder**
- Click and hold the drag handle
- Drag the value up or down to the desired position
- Release to drop it in place

### 3. **Visual Feedback**
- **Dragging**: Item fades slightly (50% opacity) and background highlights
- **Target**: Clear indication of where the item will be placed
- **Smooth Animation**: CSS transforms for smooth dragging

### 4. **Full List Height**
- Enum list container now has increased max-height (200px)
- Scrollable if you have many enum values
- Border around the list for clarity

## How to Use

### Step-by-Step: Adding and Reordering Enum Values

#### 1. **Add Enum Values**
   ```
   Input Field: "Add Enum Value"
   - Type your value
   - Press Enter OR click the + button
   - Value appears in the list below
   ```

#### 2. **Reorder Values by Dragging**
   ```
   For each value in the list:
   ≡  active          [X]
   ≡  pending         [X]
   ≡  completed       [X]
   
   To move "pending" between "active" and "completed":
   1. Position mouse over the ≡ handle next to "pending"
   2. Click and hold the handle
   3. Drag downward
   4. Release when it's in the desired position
   ```

#### 3. **Alternative: Use Sort Buttons**
   ```
   Top of enum section has two sort buttons:
   [A→Z] - Sort alphabetically ascending
   [Z→A] - Sort alphabetically descending
   ```

#### 4. **Remove Values**
   ```
   Click the X button on the right side of any value
   Value is removed from the list
   ```

## Use Cases

### Example 1: Status Enum
```
Default Order (Added sequentially):
1. active
2. pending
3. cancelled
4. completed

Desired Order (by workflow):
1. pending      ← Move up
2. active
3. completed    ← Move down
4. cancelled    ← Move down
```

### Example 2: Priority Enum
```
Added in random order:
- low
- high
- critical
- medium

Desired Order (by priority):
- critical      ← Highest priority first
- high
- medium
- low           ← Lowest priority last
```

### Example 3: Size Enum
```
Logical grouping order:
- small
- medium
- large
- extra-large

Can drag to arrange without re-entering values
```

## Tips & Tricks

### 1. **Drag Precision**
   - Drag handle has 8px activation distance (prevents accidental drags on click)
   - Click once to select, drag to move
   - Hold for a moment before dragging for best results

### 2. **Mobile/Touch**
   - Works on touch devices too!
   - Touch and hold the drag handle
   - Slide up or down to reorder
   - Release to drop

### 3. **Keyboard Navigation**
   - Tab to focus on items
   - Arrow keys work with dnd-kit for keyboard reordering
   - Full keyboard accessibility

### 4. **Batch Reordering**
   - Add all values first, then reorder them all
   - Combine with sort buttons for complex arrangements
   - Sort A-Z, then manually adjust critical items

### 5. **Long Lists**
   - List container has scrollbar for many values
   - Scroll while dragging near the edges (manual scroll required)
   - Consider grouping very long lists

## Visual Elements

### List Layout
```
┌─────────────────────────────────┐
│ Allowed Values (Enum)    [A→Z] [Z→A]  ← Buttons
├─────────────────────────────────┤
│ ≡  value1              [X]      ← Drag handle, Value, Delete
│ ≡  value2              [X]
│ ≡  value3              [X]
│                                  
│ Add Enum Value        [+]        ← Input field, Add button
└─────────────────────────────────┘
```

### States

#### Normal State
```
≡  active              [X]
```

#### Hover State
```
≡  active              [X]  ← Drag handle color slightly darker
```

#### Dragging State
```
≡  pending             [X]  ← Background highlighted, opacity 50%
   (faded while dragging)
```

#### Over Target
```
≡  active              [X]  ← Shows where item will land
≡  [PENDING HERE]
≡  completed           [X]
```

## Common Questions

### Q: How do I undo a reorder?
**A:** The order is updated immediately. If you made a mistake:
1. Drag the item back to its previous position, or
2. Use the sort buttons (A-Z or Z-A) to reset alphabetically

### Q: Can I reorder while in mobile view?
**A:** Yes! Touch and drag works the same way as mouse dragging.

### Q: What happens if I drag an item outside the list?
**A:** Dropping outside the list area cancels the drag operation. The item returns to its original position.

### Q: How many enum values can I have?
**A:** Technically unlimited, but the list maxes out at 200px height with scrolling.

### Q: Can I preserve the order when sorting?
**A:** No, the A-Z and Z-A buttons replace your custom order with alphabetical order. If you need to preserve it, manually reorder instead.

### Q: Does the order affect how the enum values are used?
**A:** Yes! The order you set here is reflected in:
- Form displays (dropdowns, radio buttons)
- API documentation
- Generated examples
- Validation error messages

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Tab | Focus next item |
| Shift+Tab | Focus previous item |
| Arrow Up | (With dnd-kit enabled) Move up |
| Arrow Down | (With dnd-kit enabled) Move down |
| Enter | Confirm drag operation |
| Escape | Cancel drag operation |

## Best Practices

### 1. **Organize by Frequency**
   - Put most commonly used values first
   - Users see them immediately without scrolling

### 2. **Logical Grouping**
   - Group related statuses together
   - Group by priority or importance
   - Natural workflow order

### 3. **User Expectations**
   - Follow industry standard ordering
   - Status: pending → active → completed
   - Priority: critical → high → medium → low

### 4. **Documentation**
   - Note the enum order in your schema documentation
   - Explain why this order was chosen
   - Helps future maintainers

### 5. **Testing**
   - Verify generated examples use the correct enum order
   - Check API documentation shows correct order
   - Validate client-side forms reflect the order

## Troubleshooting

### Dragging doesn't work
- Ensure you're clicking and holding the drag handle (≡)
- Not clicking on the value text itself
- Try waiting a moment before dragging

### Item snaps back to original position
- Check if drag ended over the same position
- Try dragging to a clearly different position
- Refresh page if behavior is unexpected

### List is too small to see all values
- Scroll within the list using the scrollbar
- Consider reducing enum values if too many
- Max height is 200px (by design for form layout)

### Value disappeared after dragging
- Check the scroll position (might be off-screen)
- Verify it wasn't accidentally deleted
- Check browser console for any errors

## Feature Integration

This feature works seamlessly with:

- ✅ **Add Enum Value** - Add new values, then reorder
- ✅ **Remove Enum Value** - Delete values without affecting order
- ✅ **Sort A-Z** - Quick alphabetic sort
- ✅ **Sort Z-A** - Quick reverse alphabetic sort
- ✅ **Type Validation** - All ordering preserves type constraints
- ✅ **Default Values** - Order doesn't affect default value selection
- ✅ **Example Generation** - Uses first value regardless of order

## Related Features

- **Property Title** - Descriptive name for the property
- **Description** - Explain what this enum represents
- **Default Value** - Set a recommended default enum value
- **Required** - Mark if this enum must always be provided
- **Deprecated** - Mark if this enum value is no longer recommended

## See Also

- Enum Value Reordering Feature Documentation: `ENUM_REORDERING_FEATURE.md`
- Property Form Reference
- OpenAPI/JSON Schema Enum Specification

