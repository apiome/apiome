# Tuple Mode UI Preview

## Property Dialog - Array Constraints Section

```
┌─────────────────────────────────────────────────────────────────┐
│ Array Constraints                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Min Items: [    ]           Max Items: [    ]                 │
│                                                                 │
│  ☐ Unique Items (no duplicates)                                │
│                                                                 │
│  Contains (JSON Schema):                                        │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ {"type": "string", "minLength": 5}                        │ │
│  └───────────────────────────────────────────────────────────┘ │
│  OpenAPI 3.1: JSON Schema that at least one item must match    │
│                                                                 │
│  [If contains is set, show minContains/maxContains fields]     │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ ☑ Tuple Mode (prefixItems)                                  │ │
│ │    OpenAPI 3.1: Define ordered schemas for specific         │ │
│ │    positions                                                 │ │
│ │                                                              │ │
│ │ Define schemas for specific array positions. Items beyond   │ │
│ │ these positions will use the regular items schema.          │ │
│ │                                                              │ │
│ │ ┌──────────────────────────────────────────────────────────┐│ │
│ │ │ ⋮  Position 0   [string ▼]                       [🗑️]   ││ │
│ │ │                                                           ││ │
│ │ │ ┌───────────────────────────────────────────────────────┐││ │
│ │ │ │ {                                                     │││ │
│ │ │ │   "type": "string",                                   │││ │
│ │ │ │   "minLength": 1,                                     │││ │
│ │ │ │   "description": "Name"                               │││ │
│ │ │ │ }                                                     │││ │
│ │ │ └───────────────────────────────────────────────────────┘││ │
│ │ │ JSON Schema for this position                            ││ │
│ │ └──────────────────────────────────────────────────────────┘│ │
│ │                                                              │ │
│ │ ┌──────────────────────────────────────────────────────────┐│ │
│ │ │ ⋮  Position 1   [number ▼]                       [🗑️]   ││ │
│ │ │                                                           ││ │
│ │ │ ┌───────────────────────────────────────────────────────┐││ │
│ │ │ │ {                                                     │││ │
│ │ │ │   "type": "number",                                   │││ │
│ │ │ │   "minimum": 0,                                       │││ │
│ │ │ │   "description": "Age"                                │││ │
│ │ │ │ }                                                     │││ │
│ │ │ └───────────────────────────────────────────────────────┘││ │
│ │ │ JSON Schema for this position                            ││ │
│ │ └──────────────────────────────────────────────────────────┘│ │
│ │                                                              │ │
│ │ [+ Add Position]                                             │ │
│ │                                                              │ │
│ │ Example: For a tuple like [string, number, boolean],        │ │
│ │ define 3 positions with types string, number, and boolean   │ │
│ │ respectively.                                                │ │
│ │                                                              │ │
│ │ Items Schema (for positions beyond prefix):                 │ │
│ │ ┌───────────────────────────────────────────────────────┐   │ │
│ │ │ false                                                 │   │ │
│ │ └───────────────────────────────────────────────────────┘   │ │
│ │ JSON Schema for items beyond the defined prefix positions  │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Component Interactions

### Adding a Position

1. User clicks **[+ Add Position]**
2. New position appears with:
   - Drag handle (⋮)
   - Position number (auto-incremented)
   - Type dropdown (defaults to "string")
   - JSON editor textarea
   - Delete button (🗑️)

### Reordering Positions

1. User clicks and holds the drag handle (⋮)
2. Position card becomes semi-transparent (opacity: 0.5)
3. User drags up or down
4. Drop zone highlights
5. Release to drop in new position
6. Position numbers update automatically

### Editing a Position Schema

1. User edits JSON in textarea
2. Real-time JSON validation
3. If invalid: Red border + error message "Invalid JSON"
4. If valid: Schema updates immediately
5. Type dropdown stays in sync with schema.type

### Items Schema Options

| User Input | Resulting Behavior |
|------------|-------------------|
| `true` | Any additional items allowed (default) |
| `false` | No additional items allowed (strict tuple) |
| `{"type": "string"}` | Additional items must be strings |
| Empty | Defaults to `true` |

### Enabling/Disabling Tuple Mode

**Enabling:**
- User checks "Tuple Mode" checkbox
- PrefixItems editor appears with empty state
- "Add Position" button is visible
- Items schema field appears

**Disabling:**
- User unchecks "Tuple Mode" checkbox
- Confirmation dialog: "This will remove all prefix items. Continue?"
- If confirmed: PrefixItems editor disappears, data cleared
- Regular array items schema is preserved

## Visual States

### Empty State (No Positions)
```
┌─────────────────────────────────────────────────────────────┐
│  No prefix items defined. Click "Add Position" to define   │
│  schemas for specific array positions.                      │
└─────────────────────────────────────────────────────────────┘

[+ Add Position]
```

### Active State (With Positions)
```
Position cards with drag handles, type selectors, and delete buttons
```

### Dragging State
```
Position card becomes semi-transparent
Drag indicator shows where it will drop
Other cards shift to make space
```

### Error State (Invalid JSON)
```
┌───────────────────────────────────────────────────────────┐
│ { "type": "string",  ← Missing closing brace              │
└───────────────────────────────────────────────────────────┘
❌ Invalid JSON
```

## Type Dropdown Options

```
[string  ▼]
  ├─ Any
  ├─ string
  ├─ number
  ├─ integer
  ├─ boolean
  ├─ object
  ├─ array
  └─ null
```

## Helper Text Examples

### Below Tuple Mode Checkbox
> OpenAPI 3.1: Define ordered schemas for specific positions

### Below Position Editor
> Example: For a tuple like [string, number, boolean], define 3 positions with types string, number, and boolean respectively.

### Below Items Schema Field
> JSON Schema for items beyond the defined prefix positions

## Color Scheme (Material-UI)

- **Primary**: Button actions, checkboxes
- **Background (default)**: Position card backgrounds
- **Divider**: Card borders
- **Text (secondary)**: Helper text, labels
- **Error**: Invalid JSON borders and text

## Responsive Behavior

- **Desktop**: Full width, all features visible
- **Tablet**: Slightly compressed, maintains functionality
- **Mobile**: Stacked layout, touch-friendly drag handles

## Accessibility

- **Keyboard Navigation**: Tab through fields, arrow keys in dropdowns
- **Screen Readers**: ARIA labels on all interactive elements
- **Focus Indicators**: Clear focus states on all inputs
- **Error Announcements**: Screen readers announce validation errors

