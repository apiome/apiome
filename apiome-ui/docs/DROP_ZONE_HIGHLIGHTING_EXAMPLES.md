# Drop Zone Highlighting: Visual Examples

## Example 1: Simple Object with Children

### Before Hovering
```
┌────────────────────────────────────────────┐
│ Person                                      │
├────────────────────────────────────────────┤
│ A person entity                            │
├────────────────────────────────────────────┤
│ ▼ name: string                             │  White
│   email: string                            │  Gray
│ ▼ address: object                (3)       │  White
│     street: string                         │  Gray
│     city: string                           │  White
│     zipCode: string                        │  Gray
│   age: number                              │  White
└────────────────────────────────────────────┘
```

### While Dragging Over "address: object"
```
┌────────────────────────────────────────────┐
│ Person                                      │
├────────────────────────────────────────────┤
│ A person entity                            │
├────────────────────────────────────────────┤
│ ▼ name: string                             │  White
│   email: string                            │  Gray
│ ▼ address: object                (3)       │  🟢 GREEN (drop zone!)
│     street: string                         │  🟢 GREEN (in drop zone!)
│     city: string                           │  🟢 GREEN (in drop zone!)
│     zipCode: string                        │  🟢 GREEN (in drop zone!)
│   age: number                              │  White
└────────────────────────────────────────────┘

All properties within the "address" object are highlighted!
```

## Example 2: Deeply Nested Structure

### Before Hovering
```
┌────────────────────────────────────────────┐
│ Company                                     │
├────────────────────────────────────────────┤
│ A company entity                           │
├────────────────────────────────────────────┤
│ ▼ name: string                             │  White
│ ▼ contact: object                  (2)     │  Gray
│   ▼ address: object                (3)     │  White
│       street: string                       │  Gray
│       city: string                         │  White
│       zipCode: string                      │  Gray
│     phone: string                          │  White
│   employees: number                        │  Gray
└────────────────────────────────────────────┘
```

### While Dragging Over "contact: object"
```
┌────────────────────────────────────────────┐
│ Company                                     │
├────────────────────────────────────────────┤
│ A company entity                           │
├────────────────────────────────────────────┤
│ ▼ name: string                             │  White
│ ▼ contact: object                  (2)     │  🟢 GREEN (drop zone!)
│   ▼ address: object                (3)     │  🟢 GREEN (nested in drop zone!)
│       street: string                       │  🟢 GREEN (nested in drop zone!)
│       city: string                         │  🟢 GREEN (nested in drop zone!)
│       zipCode: string                      │  🟢 GREEN (nested in drop zone!)
│     phone: string                          │  🟢 GREEN (in drop zone!)
│   employees: number                        │  Gray
└────────────────────────────────────────────┘

All descendants of "contact", including nested "address", are highlighted!
```

### While Dragging Over "address: object" (nested)
```
┌────────────────────────────────────────────┐
│ Company                                     │
├────────────────────────────────────────────┤
│ A company entity                           │
├────────────────────────────────────────────┤
│ ▼ name: string                             │  White
│ ▼ contact: object                  (2)     │  Gray
│   ▼ address: object                (3)     │  🟢 GREEN (drop zone!)
│       street: string                       │  🟢 GREEN (in drop zone!)
│       city: string                         │  🟢 GREEN (in drop zone!)
│       zipCode: string                      │  🟢 GREEN (in drop zone!)
│     phone: string                          │  White
│   employees: number                        │  Gray
└────────────────────────────────────────────┘

Only "address" and its children are highlighted!
```

## Example 3: Mixed Property Types

### Structure
```
┌────────────────────────────────────────────┐
│ Product                                     │
├────────────────────────────────────────────┤
│ A product in the catalog                   │
├────────────────────────────────────────────┤
│ ▼ id: string                               │  White
│   name: string                             │  Gray
│   price: number                            │  White
│ ▼ dimensions: object           (3)         │  Gray
│     width: number                          │  White
│     height: number                         │  Gray
│     depth: number                          │  White
│   inStock: boolean                         │  Gray
│ ▼ reviews: Review[]                        │  White
└────────────────────────────────────────────┘
```

### Dragging Over "dimensions: object"
```
┌────────────────────────────────────────────┐
│ Product                                     │
├────────────────────────────────────────────┤
│ A product in the catalog                   │
├────────────────────────────────────────────┤
│ ▼ id: string                               │  White
│   name: string                             │  Gray
│   price: number                            │  White
│ ▼ dimensions: object           (3)         │  🟢 GREEN (drop zone!)
│     width: number                          │  🟢 GREEN (in drop zone!)
│     height: number                         │  🟢 GREEN (in drop zone!)
│     depth: number                          │  🟢 GREEN (in drop zone!)
│   inStock: boolean                         │  Gray
│ ▼ reviews: Review[]                        │  White
└────────────────────────────────────────────┘

Only object properties and their children can be drop zones!
```

### Dragging Over "inStock: boolean" (non-object)
```
┌────────────────────────────────────────────┐
│ Product                                     │
├────────────────────────────────────────────┤
│ Drop property here                         │  🟢 GREEN (main node hint!)
├────────────────────────────────────────────┤
│ ▼ id: string                               │  White
│   name: string                             │  Gray
│   price: number                            │  White
│ ▼ dimensions: object           (3)         │  Gray
│     width: number                          │  White
│     height: number                         │  Gray
│     depth: number                          │  White
│   inStock: boolean                         │  Gray (no highlight!)
│ ▼ reviews: Review[]                        │  White
└────────────────────────────────────────────┘

Non-object properties can't accept drops, so they don't highlight.
Instead, the main node shows "Drop property here"!
```

## Example 4: Collapsed vs Expanded

### Collapsed Object
```
┌────────────────────────────────────────────┐
│ ▶ address: object              (3)         │  White
│   phone: string                            │  Gray
└────────────────────────────────────────────┘
```

### Dragging Over Collapsed "address"
```
┌────────────────────────────────────────────┐
│ ▶ address: object              (3)         │  🟢 GREEN (drop zone!)
│   phone: string                            │  Gray (not highlighted)
└────────────────────────────────────────────┘

Children are hidden, so they're not highlighted.
Only the parent shows as a drop zone.
```

### Expanded Object
```
┌────────────────────────────────────────────┐
│ ▼ address: object              (3)         │  White
│     street: string                         │  Gray
│     city: string                           │  White
│     zipCode: string                        │  Gray
│   phone: string                            │  White
└────────────────────────────────────────────┘
```

### Dragging Over Expanded "address"
```
┌────────────────────────────────────────────┐
│ ▼ address: object              (3)         │  🟢 GREEN (drop zone!)
│     street: string                         │  🟢 GREEN (visible, highlighted!)
│     city: string                           │  🟢 GREEN (visible, highlighted!)
│     zipCode: string                        │  🟢 GREEN (visible, highlighted!)
│   phone: string                            │  White
└────────────────────────────────────────────┘

All visible children are now highlighted!
```

## Color Reference

| State | Background Color | Hex Code | Description |
|-------|------------------|----------|-------------|
| In Drop Zone | Light Green | `#d1fae5` | Property is in the active drop zone |
| Even Row | White | `white` | Normal state (even index) |
| Odd Row | Light Gray | `#fafafa` | Normal state (odd index) |

## Transition Effect

All background color changes use:
```css
transition: background 0.2s
```

This creates a smooth fade between colors when:
- Entering a drop zone (white/gray → green)
- Leaving a drop zone (green → white/gray)

## User Experience Flow

```
1. User starts dragging a property
   ↓
2. User moves cursor over class node
   → Main description area shows "Drop property here"
   ↓
3. User moves cursor over a string/number property
   → "Drop property here" stays visible (property doesn't highlight)
   ↓
4. User moves cursor over an object property
   → "Drop property here" disappears
   → Object property highlights in green
   → All nested children highlight in green
   ↓
5. User sees the entire drop zone clearly!
   → Can confidently drop the property
   ↓
6. Property is nested under the highlighted object
```

## Visual Clarity Benefits

### Before (Only Parent Highlighted)
❌ **Confusing**: "Will my property be nested here or added alongside?"
❌ **Unclear scope**: "What's actually part of this object?"
❌ **Ambiguous**: "Do the children matter?"

### After (Entire Drop Zone Highlighted)
✅ **Clear**: "This entire section is the drop zone"
✅ **Obvious scope**: "All these green items are part of the target object"
✅ **Confident**: "I know exactly where my property will go"

## Implementation Note

The highlighting uses a recursive parent-chain walk to determine ancestry:
```typescript
isDescendantOfDraggedProperty(childId, parentId)
  → walks up parent_id chain
  → returns true if parent is found in chain
  → O(depth) complexity (typically 1-3 levels)
```

This ensures that even deeply nested properties are correctly identified as part of the drop zone.

