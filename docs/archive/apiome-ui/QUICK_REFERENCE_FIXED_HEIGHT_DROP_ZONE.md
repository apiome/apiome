# Quick Reference: Fixed-Height Drop Zone

## ✅ Problem Solved
Drag and drop "Drop property here" message no longer causes jumping/flickering.

## 🔧 Solution
Single fixed-height area (31.2px) that swaps content between description and drop hint.

## 📏 Key Measurements
- **Height**: `31.2px` (EXACT, not min/max)
- **Font**: `11px`
- **Line Height**: `1.4`
- **Padding**: `8px 12px`

## 🎨 Critical CSS Properties
```css
height: 31.2px;              /* Fixed height (no min/max) */
overflow: hidden;            /* Hide overflow */
text-overflow: ellipsis;     /* Show ... for long text */
white-space: nowrap;         /* Don't wrap (required for ellipsis) */
display: flex;               /* Enable flexbox */
align-items: center;         /* Vertical centering */
transition: all 0.15s ease;  /* Smooth color transitions */
```

## 📝 Content Logic
```typescript
{dragTarget === 'node' ? 'Drop property here' : (typedData.description || '\u00A0')}
```

- **Dragging over node**: Show "Drop property here"
- **Not dragging, has description**: Show description (with ellipsis if long)
- **Not dragging, no description**: Show non-breaking space

## 🎯 What This Achieves
✅ Zero layout shifts  
✅ No DOM mutations during drag  
✅ Long descriptions truncate cleanly  
✅ Constant node dimensions  
✅ Smooth CSS transitions  
✅ No flickering or jumping  

## 🚀 Performance
- **Before**: Multiple layout reflows per drag movement
- **After**: Zero layout reflows (only text content changes)

## 📍 Location
`/apiome-ui/src/app/components/ade/studio/ClassNode.tsx`

Lines ~307-327

## 📚 Full Documentation
- `DRAG_DROP_FINAL_SOLUTION.md` - Complete technical docs
- `ELLIPSIS_OVERFLOW_EXAMPLE.md` - Visual examples
- `IMPLEMENTATION_SUMMARY_FIXED_HEIGHT_DROP_ZONE.md` - Full summary

## 🧪 Testing
```bash
cd apiome-ui
npm run build  # Should succeed with no errors
```

## 🎨 Drop Zone Visual Highlighting (NEW)
When dragging over an object-type property, **all nested children are highlighted** with the same color, making the entire drop zone visible.

**Example:**
```
✓ address: object      ← Highlighted (green)
✓   street: string     ← Also highlighted (green)
✓   city: string       ← Also highlighted (green)
```

See `DROP_ZONE_VISUAL_HIGHLIGHTING.md` for details.

## 💡 Key Insight
**Don't add/remove elements - swap their content within a fixed container.**

This eliminates layout thrashing and creates a smooth, stable UX.

