# Nested Properties Visual Example

## Before and After

### Before: Flat Property Structure

```
┌─────────────────────────────────────┐
│ User                           [×]  │
├─────────────────────────────────────┤
│ id              string    [✎] [×]  │
│ name            string    [✎] [×]  │
│ email           string    [✎] [×]  │
│ street          string    [✎] [×]  │
│ city            string    [✎] [×]  │
│ state           string    [✎] [×]  │
│ zipCode         string    [✎] [×]  │
│ phone           string    [✎] [×]  │
└─────────────────────────────────────┘
```

### After: Hierarchical Property Structure

```
┌─────────────────────────────────────┐
│ User                           [×]  │
├─────────────────────────────────────┤
│ id              string    [✎] [×]  │
│ name            string    [✎] [×]  │
│ email           string    [✎] [×]  │
│ ▼ address (4)   object    [✎] [×]  │
│   └ street      string    [✎] [×]  │
│   └ city        string    [✎] [×]  │
│   └ state       string    [✎] [×]  │
│   └ zipCode     string    [✎] [×]  │
│ phone           string    [✎] [×]  │
└─────────────────────────────────────┘
```

## Interaction Flow

### Step 1: Initial State
```
┌─────────────────────────────────────┐
│ User                           [×]  │
├─────────────────────────────────────┤
│ id              string    [✎] [×]  │
│ name            string    [✎] [×]  │
│ email           string    [✎] [×]  │
│ ▶ address       object    [✎] [×]  │  ← Collapsed (no children visible)
│ phone           string    [✎] [×]  │
└─────────────────────────────────────┘
```

### Step 2: Click Chevron to Expand
```
┌─────────────────────────────────────┐
│ User                           [×]  │
├─────────────────────────────────────┤
│ id              string    [✎] [×]  │
│ name            string    [✎] [×]  │
│ email           string    [✎] [×]  │
│ ▼ address (0)   object    [✎] [×]  │  ← Expanded (but no children yet)
│                                     │  ← Empty space for children
│ phone           string    [✎] [×]  │
└─────────────────────────────────────┘
```

### Step 3: Drag Property Over Object Property
```
┌─────────────────────────────────────┐     ┌──────────────┐
│ User                           [×]  │     │ PROPERTIES   │
├─────────────────────────────────────┤     ├──────────────┤
│ id              string    [✎] [×]  │     │ street       │ ←─┐
│ name            string    [✎] [×]  │     └──────────────┘   │ Dragging
│ email           string    [✎] [×]  │                         │
│ ▼ address (0)   object    [✎] [×]  │ ← Green highlight!     │
│                                     │                         │
│ phone           string    [✎] [×]  │                        ─┘
└─────────────────────────────────────┘
```

### Step 4: Drop Property
```
┌─────────────────────────────────────┐
│ User                           [×]  │
├─────────────────────────────────────┤
│ id              string    [✎] [×]  │
│ name            string    [✎] [×]  │
│ email           string    [✎] [×]  │
│ ▼ address (1)   object    [✎] [×]  │  ← Child count updated
│   └ street      string    [✎] [×]  │  ← New child property!
│ phone           string    [✎] [×]  │
└─────────────────────────────────────┘
```

### Step 5: Add More Children
```
┌─────────────────────────────────────┐
│ User                           [×]  │
├─────────────────────────────────────┤
│ id              string    [✎] [×]  │
│ name            string    [✎] [×]  │
│ email           string    [✎] [×]  │
│ ▼ address (4)   object    [✎] [×]  │
│   └ street      string    [✎] [×]  │
│   └ city        string    [✎] [×]  │
│   └ state       string    [✎] [×]  │
│   └ zipCode     string    [✎] [×]  │
│ phone           string    [✎] [×]  │
└─────────────────────────────────────┘
```

### Step 6: Collapse to Clean View
```
┌─────────────────────────────────────┐
│ User                           [×]  │
├─────────────────────────────────────┤
│ id              string    [✎] [×]  │
│ name            string    [✎] [×]  │
│ email           string    [✎] [×]  │
│ ▶ address (4)   object    [✎] [×]  │  ← Collapsed but shows count
│ phone           string    [✎] [×]  │
└─────────────────────────────────────┘
```

## Multi-Level Nesting Example

### Product with Nested Dimensions

```
┌──────────────────────────────────────────┐
│ Product                             [×]  │
├──────────────────────────────────────────┤
│ id                string    [✎] [×]     │
│ name              string    [✎] [×]     │
│ price             number    [✎] [×]     │
│ ▼ details (3)     object    [✎] [×]     │  ← Level 1
│   └ description   string    [✎] [×]     │  ← Level 2
│   └ weight        number    [✎] [×]     │  ← Level 2
│   └ ▼ dimensions (3) object [✎] [×]     │  ← Level 2 (parent)
│       └ width     number    [✎] [×]     │  ← Level 3
│       └ height    number    [✎] [×]     │  ← Level 3
│       └ depth     number    [✎] [×]     │  ← Level 3
│ inStock           boolean   [✎] [×]     │
└──────────────────────────────────────────┘
```

### Collapsed View

```
┌──────────────────────────────────────────┐
│ Product                             [×]  │
├──────────────────────────────────────────┤
│ id                string    [✎] [×]     │
│ name              string    [✎] [×]     │
│ price             number    [✎] [×]     │
│ ▶ details (3)     object    [✎] [×]     │  ← All nested content hidden
│ inStock           boolean   [✎] [×]     │
└──────────────────────────────────────────┘
```

## Color and Visual Indicators

### Hover States

**Normal State:**
```
│ ▶ address (4)   object    [✎] [×]  │
```

**Hovering over Chevron:**
```
│ ▶ address (4)   object    [✎] [×]  │
  ↑ (darker color)
```

**Hovering over Edit Button:**
```
│ ▶ address (4)   object    [✎] [×]  │
                              ↑ (blue background)
```

**Hovering over Delete Button:**
```
│ ▶ address (4)   object    [✎] [×]  │
                                  ↑ (red background)
```

### Drag-Over State

**Dragging property over object:**
```
│ ▼ address (4)   object    [✎] [×]  │  ← Green background (#d1fae5)
```

**Dragging property over non-object:**
```
│ name            string    [✎] [×]  │  ← No highlight (invalid drop)
```

## Row Background Pattern

Alternating backgrounds for better readability:

```
│ id              string    [✎] [×]  │  ← White (even index: 0)
│ name            string    [✎] [×]  │  ← Gray (odd index: 1)
│ email           string    [✎] [×]  │  ← White (even index: 2)
│ ▼ address (4)   object    [✎] [×]  │  ← Gray (odd index: 3)
│   └ street      string    [✎] [×]  │  ← White (even index: 4)
│   └ city        string    [✎] [×]  │  ← Gray (odd index: 5)
│   └ state       string    [✎] [×]  │  ← White (even index: 6)
│   └ zipCode     string    [✎] [×]  │  ← Gray (odd index: 7)
│ phone           string    [✎] [×]  │  ← White (even index: 8)
```

## Read-Only Mode

In read-only mode (published versions):

```
┌─────────────────────────────────────┐
│ User                           [×]  │  ← Delete button hidden in read-only
├─────────────────────────────────────┤
│ id              string              │  ← No edit/delete buttons
│ name            string              │
│ email           string              │
│ ▼ address (4)   object              │  ← Chevron still works!
│   └ street      string              │
│   └ city        string              │
│   └ state       string              │
│   └ zipCode     string              │
│ phone           string              │
└─────────────────────────────────────┘
```

**Note:** In read-only mode:
- ✅ Chevrons still work (viewing hierarchy is allowed)
- ❌ Drag-and-drop is disabled
- ❌ Edit/delete buttons are hidden
- ❌ Cannot modify structure

## JSON Schema Representation

The UI hierarchy maps to this JSON Schema:

```json
{
  "User": {
    "type": "object",
    "properties": {
      "id": { "type": "string" },
      "name": { "type": "string" },
      "email": { "type": "string" },
      "address": {
        "type": "object",
        "properties": {
          "street": { "type": "string" },
          "city": { "type": "string" },
          "state": { "type": "string" },
          "zipCode": { "type": "string" }
        }
      },
      "phone": { "type": "string" }
    }
  }
}
```

## OpenAPI Representation

In OpenAPI 3.0 specification:

```yaml
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: string
        name:
          type: string
        email:
          type: string
        address:
          type: object
          properties:
            street:
              type: string
            city:
              type: string
            state:
              type: string
            zipCode:
              type: string
        phone:
          type: string
```

## Summary

The nested properties UI provides:
- ✅ Visual hierarchy with indentation
- ✅ Expand/collapse interaction
- ✅ Drag-and-drop to create nesting
- ✅ Visual feedback during interactions
- ✅ Clean, organized display
- ✅ Read-only mode support
- ✅ Standards-compliant output (JSON Schema, OpenAPI)

