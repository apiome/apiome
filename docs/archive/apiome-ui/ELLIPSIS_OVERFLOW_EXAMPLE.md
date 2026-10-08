# Ellipsis Overflow Visual Example

## The Fixed-Height Area in Action

### Before Fix (Variable Height)
```
┌─────────────────────────────────────────┐
│ Class: Person                           │
├─────────────────────────────────────────┤
│ This is a very long description that    │
│ wraps to multiple lines and causes      │  ← Variable height
│ the node to be taller                   │     causes jumping!
└─────────────────────────────────────────┘

[Drag starts - "Drop property here" element ADDED]

┌─────────────────────────────────────────┐
│ Class: Person                           │
├─────────────────────────────────────────┤
│ This is a very long description that    │
│ wraps to multiple lines and causes      │
│ the node to be taller                   │
├─────────────────────────────────────────┤
│      Drop property here                 │  ← NEW element
└─────────────────────────────────────────┘  ← Height increased!
     ↑ Node jumped down!
```

### After Fix (Fixed Height with Ellipsis)
```
┌─────────────────────────────────────────┐
│ Class: Person                           │
├─────────────────────────────────────────┤
│ This is a very long description tha...  │  ← Ellipsis!
└─────────────────────────────────────────┘     31.2px fixed
     ↑ Always exactly 31.2px tall

[Drag starts - Content SWAPS (same element)]

┌─────────────────────────────────────────┐
│ Class: Person                           │
├─────────────────────────────────────────┤
│        Drop property here               │  ← Content swapped
└─────────────────────────────────────────┘     31.2px fixed
     ↑ Still exactly 31.2px tall - NO MOVEMENT!
```

## CSS Implementation

### The Three Critical Properties for Ellipsis

```css
overflow: hidden;         /* Hide overflowing text */
text-overflow: ellipsis;  /* Show ... for hidden text */
white-space: nowrap;      /* Prevent line wrapping */
```

Without `nowrap`, text would wrap to multiple lines.
Without `overflow: hidden`, text would extend beyond container.
Without `text-overflow: ellipsis`, text would just be cut off.

### Fixed Height Calculation

```
Font size:      11px
Line height:    1.4
Text height:    11 × 1.4 = 15.4px
Padding:        8px + 8px = 16px
Total:          15.4 + 16 = 31.4px

Used 31.2px for pixel-perfect rendering
```

## Real-World Examples

### Example 1: Short Description
```
Normal state:
┌────────────────────────────┐
│ A person entity            │  ← Full text visible
└────────────────────────────┘
    31.2px

Drag state:
┌────────────────────────────┐
│  Drop property here        │  ← Swap
└────────────────────────────┘
    31.2px (unchanged)
```

### Example 2: Long Description
```
Normal state:
┌────────────────────────────┐
│ A comprehensive person ...  │  ← Truncated with ellipsis
└────────────────────────────┘
    31.2px

Drag state:
┌────────────────────────────┐
│  Drop property here        │  ← Swap
└────────────────────────────┘
    31.2px (unchanged)
```

### Example 3: Very Long Description
```
Normal state:
┌────────────────────────────┐
│ This is an extremely lo... │  ← Much longer text truncated
└────────────────────────────┘
    31.2px

Drag state:
┌────────────────────────────┐
│  Drop property here        │  ← Swap
└────────────────────────────┘
    31.2px (unchanged)
```

### Example 4: No Description
```
Normal state:
┌────────────────────────────┐
│                            │  ← Non-breaking space (\u00A0)
└────────────────────────────┘
    31.2px

Drag state:
┌────────────────────────────┐
│  Drop property here        │  ← Swap
└────────────────────────────┘
    31.2px (unchanged)
```

## Hover Behavior Comparison

### Before (Jumping)
```
[Cursor at position X, Y]
Node height: 100px

[Move cursor 1px]
"Drop property here" appears
Node height: 130px          ← Content shifts!
Cursor now at position X, Y-30  ← Relative position changed!

[DragLeave fires because cursor "moved" out]
"Drop property here" disappears
Node height: 100px
Cursor back at position X, Y

[Repeat rapidly] = JUMPING!
```

### After (Stable)
```
[Cursor at position X, Y]
Node height: 100px

[Move cursor 1px]
Content swaps to "Drop property here"
Node height: 100px          ← No change!
Cursor still at position X, Y   ← No movement!

[No DragLeave - cursor never "left"]
Content stays "Drop property here"
Node height: 100px

[Move smoothly] = NO JUMPING!
```

## Key Insight

**The problem was never about the drag events themselves.**

The problem was that **layout changes caused by DOM mutations** were moving the cursor's relative position within the node, which triggered new drag events, which triggered layout changes, creating an infinite loop.

**The solution**: Keep the layout absolutely static by using a fixed-height container that only swaps its text content, never its dimensions.

## Testing Checklist

✅ Class with no description: Shows space, swaps to hint  
✅ Class with short description: Shows full text, swaps to hint  
✅ Class with medium description: Shows full text, swaps to hint  
✅ Class with long description: Shows ellipsis, swaps to hint  
✅ Class with very long description: Shows ellipsis, swaps to hint  
✅ Drag over node: Hint appears and stays stable  
✅ Drag over non-object property: Hint stays visible  
✅ Drag over object property: Hint disappears smoothly  
✅ Drag out of node: Hint disappears, description returns  
✅ No flickering at any point  
✅ No jumping at any point  
✅ Node dimensions never change  

## Browser DevTools Verification

You can verify zero layout shifts by:

1. Open Chrome DevTools
2. Press Cmd+Shift+P (Mac) or Ctrl+Shift+P (Windows/Linux)
3. Type "Show Rendering"
4. Enable "Layout Shift Regions"
5. Drag a property over a class node
6. Result: **No layout shift regions should highlight!**

This confirms zero layout thrashing.

