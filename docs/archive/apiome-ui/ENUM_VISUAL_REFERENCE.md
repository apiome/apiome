# Enumeration Reordering - Visual Reference Guide

## Drag Handle Location

### Enum List Item Structure

```
┌─────────────────────────────────────────────────┐
│  Allowed Values (Enum)              [A→Z] [Z→A] │  Header with sort buttons
├─────────────────────────────────────────────────┤
│  ≡  status_value                         [X]   │  List item
│  ≡  another_value                        [X]   │
│  ≡  final_value                          [X]   │
│                                                  │
│  [Add Enum Value________________]       [+]    │  Add new value
└─────────────────────────────────────────────────┘
│                                          
└─ Drag Handle on LEFT side
   (Three horizontal lines: ≡)
```

### Component Layout

```
PropertyFormFields Component
│
├─ Basic Fields (Title, Description)
│
├─ Type-specific Constraints
│  ├─ String constraints
│  ├─ Number constraints
│  └─ Array constraints
│
├─ Enum Section (THIS FEATURE)
│  │
│  ├─ Header: "Allowed Values (Enum)"
│  │  └─ Sort Buttons: [A→Z] [Z→A]
│  │
│  ├─ Input Row:
│  │  ├─ TextField: "Add Enum Value"
│  │  └─ IconButton: [+]
│  │
│  └─ List (DndContext + SortableContext):
│     ├─ SortableEnumItem (value 1)
│     │  ├─ DragIndicatorIcon ≡
│     │  ├─ Value text
│     │  └─ DeleteIcon [X]
│     │
│     ├─ SortableEnumItem (value 2)
│     │  ├─ DragIndicatorIcon ≡
│     │  ├─ Value text
│     │  └─ DeleteIcon [X]
│     │
│     └─ SortableEnumItem (value N)
│        ├─ DragIndicatorIcon ≡
│        ├─ Value text
│        └─ DeleteIcon [X]
│
└─ Metadata Fields (Required, Read-only, etc.)
```

## Cursor States

### Mouse Cursor Changes

```
Position               Cursor           Meaning
─────────────────────────────────────────────────────
Over drag handle ≡     👆 grab         Ready to drag
Dragging              ✊ grabbing      Currently dragging
Over value text        I text          Select text
Over delete button [X] 👆 pointer      Click to delete
Over sort button      👆 pointer      Click to sort
Input field           I text          Type here
```

## Color/Visual States

### Item Appearance

```
Normal State:
┌──────────────────────────────┐
│ ≡  value              [X]   │
└──────────────────────────────┘
│                              │
└─ Text color: normal          
└─ Background: transparent     
└─ Opacity: 100%               

Hover Drag Handle:
┌──────────────────────────────┐
│ ≡  value              [X]   │
└──────────────────────────────┘
│ ↑                            
└─ Handle color: darker/primary
└─ Cursor: grab                

Dragging:
┌──────────────────────────────┐
│ ≡  value              [X]   │
└──────────────────────────────┘
│ ↑
└─ Background: action.selected (highlight)
└─ Opacity: 50% (faded)        
└─ Cursor: grabbing            

Hover Delete:
┌──────────────────────────────┐
│ ≡  value              [X]   │
└──────────────────────────────┘
│                           ↑
└─ Delete icon color: inherit/hover
└─ Cursor: pointer
```

## Interaction Sequences

### Sequence 1: Add and Reorder

```
User Action              System Response
───────────────────────────────────────────

Type "active"           Input field updated
Press Enter             
                        → Item added to list
                        → List re-renders
                        ≡  active  [X]

Type "pending"
Press Enter             
                        → Item added to list
                        ≡  active  [X]
                        ≡  pending [X]

Type "completed"
Press Enter             
                        → Item added to list
                        ≡  active    [X]
                        ≡  pending   [X]
                        ≡  completed [X]

Click ≡ on "pending"    Drag handle active
Hold and drag down      
                        → Item background highlights
                        → Opacity reduces to 50%
                        → Cursor: grabbing
                        ≡  active    [X]
                        ≡  [pending] [X] ← being dragged
                        ≡  completed [X]

Release mouse           
                        → Drag ends
                        → arrayMove applied
                        → Order updated
                        ≡  active    [X]
                        ≡  completed [X]
                        ≡  pending   [X] ← now at bottom
```

### Sequence 2: Sort and Manual Adjust

```
User Action              System Response
───────────────────────────────────────────

List has:               (in random order)
≡  zebra  [X]
≡  apple  [X]
≡  cherry [X]

Click [A→Z] button      
                        → Items sorted A-Z
                        ≡  apple  [X]
                        ≡  cherry [X]
                        ≡  zebra  [X]

Drag "cherry" to top    
                        → Manual reorder applied
                        ≡  cherry [X]
                        ≡  apple  [X]
                        ≡  zebra  [X]
```

### Sequence 3: Keyboard Navigation

```
Key Press               System Response
───────────────────────────────────────────

Tab                     Focus moves to next item
Shift+Tab               Focus moves to previous item
                        (depends on dnd-kit configuration)

Arrow Up/Down           Navigate between items
                        (with keyboard sensor)

Enter                   Confirm drag operation
Escape                  Cancel drag operation
```

## Grid Layout

### Desktop View (Wide Screen)

```
┌──────────────────────────────────────────────────────┐
│  Property Form Fields                                │
├──────────────────────────────────────────────────────┤
│                                                      │
│  [Title Field____________________]                   │
│                                                      │
│  [Description Field_________________]                │
│  [_________________________________]                 │
│                                                      │
│  String Constraints                                  │
│  [Format__________]  [Pattern____________]           │
│  [Min Length___] [Max Length___]                     │
│                                                      │
│  Allowed Values (Enum)          [A→Z] [Z→A]         │
│  [Add Enum Value_____________] [+]                   │
│  ┌────────────────────────────────┐                  │
│  │ ≡  value1                  [X] │ (scrollable)   │
│  │ ≡  value2                  [X] │                 │
│  │ ≡  value3                  [X] │                 │
│  │ ≡  value4                  [X] │                 │
│  └────────────────────────────────┘                  │
│                                                      │
│  [Default Value_______]                              │
│                                                      │
│  Metadata:                                           │
│  ☑ Required        ☐ Read Only                       │
│  ☐ Write Only      ☐ Deprecated                      │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Mobile View (Narrow Screen)

```
┌──────────────────────┐
│  Property Fields     │
├──────────────────────┤
│                      │
│ [Title Field_____]   │
│                      │
│ [Desc Field______]   │
│ [_________________]  │
│                      │
│ Format: [_______]    │
│ Pattern: [______]    │
│                      │
│ Enum Values  [↑][↓]  │
│ [Add Value___] [+]   │
│ ┌─────────────────┐  │
│ │ ≡ val1     [X] │  │
│ │ ≡ val2     [X] │  │
│ │ ≡ val3     [X] │  │
│ │ ≡ val4     [X] │  │
│ └─────────────────┘  │
│                      │
│ [Default_______]     │
│                      │
│ ☑ Required           │
│ ☐ Read Only          │
│                      │
└──────────────────────┘
```

## Icon Reference

### Icons Used

```
Icon                 Library          Used For
─────────────────────────────────────────────────────
≡ (DragIndicator)    @mui/icons      Drag handle
+  (Add)             @mui/icons      Add enum value
X  (Delete)          @mui/icons      Remove enum
A→Z (SortByAlpha)    @mui/icons      Sort ascending
A←Z (SortByAlpha)    @mui/icons      Sort descending
                    (scaleY -1)
⌄ (ExpandMore)      @mui/icons      Expand section
^ (ExpandLess)      @mui/icons      Collapse section
```

### Icon Styling

```
Drag Handle:
  Size: small
  Color: text.secondary (gray)
  Hover: primary (blue)
  Cursor: grab/grabbing

Delete Button:
  Size: small
  Color: default
  Hover: error (red)
  Cursor: pointer

Sort Buttons:
  Size: small
  Border: 1px divider
  BorderRadius: 1
  Padding: 0.5
```

## Accessibility Markers

### Focus Indicators

```
Normal:
│ ≡  value              [X]   │

Focused (Tab):
│ ≡█ value              [X]   │  ← Focus ring around handle
  ↑
  
Focused on Delete:
│ ≡  value            █[X]█   │  ← Focus ring around delete
                      ↑
```

### ARIA Labels (via dnd-kit)

```
Elements have automatic ARIA labels:

<IconButton 
  {...attributes}     ← Contains draggable ARIA
  {...listeners}      ← Handles accessibility
>
  <DragIndicatorIcon />
</IconButton>

✅ Screen readers announce:
   "Drag handle for [value], press Space to grab"
   
✅ Keyboard users can:
   - Tab to drag handle
   - Space/Enter to grab
   - Arrow keys to move
   - Enter to drop
   - Escape to cancel
```

## Animation Timeline

### Drag Animation (milliseconds)

```
Time(ms)  Event                       Visual Effect
──────────────────────────────────────────────────
0         User clicks drag handle     Cursor: grab
0-5       Pointer down               No change
5-8       Pointer move < 8px         No drag (distance threshold)
8-100     Pointer move > 8px         Drag starts!
          
100-X     Dragging in progress       • Background highlight
                                     • Opacity: 50%
                                     • Smooth transform
                                     • Smooth transition
                                     
X-X+50    Release (drop)             • Opacity: 100%
                                     • Background fades
                                     • Items shift to new position
                                     • Animation smooth (150-200ms)

X+50      Final state                • Normal appearance
                                     • New order confirmed
                                     • Ready for next action
```

## Box Shadow & Borders

### List Container

```
┌─────────────────────────────┐
│ Border: 1px solid #divider  │
│ BorderRadius: 4px           │
│ Background: action.hover    │
│ MaxHeight: 200px            │
│ Overflow: auto (scrollable) │
└─────────────────────────────┘
```

### Individual Item

```
┌─────────────────────────────┐
│ BorderBottom: 1px #divider  │
│ Background: transparent     │
│ Display: flex               │
│ AlignItems: center          │
│ Gap: 8px                    │
└─────────────────────────────┘
```

## Scroll Behavior

```
List with many items:

┌────────────────────────────────┐
│ ≡  value1                  [X] │
│ ≡  value2                  [X] │
│ ≡  value3                  [X] │ ↑
│ ≡  value4                  [X] │ │
│ ≡  value5                  [X] │ │ 200px max height
│ ≡  value6                  [X] │ │
│ ≡  value7                  [X] │ │
│ ≡  value8                  [X] │ ↓
└────────────────────────────────┘
      ↓ (scroll bar)
      
User can:
✅ Scroll to see more items
✅ Drag while at scroll position
⚠️  Manual scroll needed (no auto-scroll)
```

---

## Quick Reference

### To Reorder Enum Values:

1. **Locate** the drag handle (≡) on the left
2. **Click and hold** the drag handle
3. **Drag** up or down to the desired position
4. **Release** to drop in place
5. ✅ Order updates immediately

### Visual Cues:

- **≡**: Drag handle (your target)
- **Gray icon**: Not hovering yet
- **Blue icon**: Hovering/ready to drag
- **Faded value**: Currently dragging
- **Highlighted row**: Drag in progress

### Alternative Methods:

- **[A→Z]**: Sort alphabetically ascending
- **[Z→A]**: Sort alphabetically descending
- **[X]**: Remove value
- **Input field**: Add new value

---

This reference guide provides complete visual information about the enumeration reordering feature for quick lookup and understanding.

