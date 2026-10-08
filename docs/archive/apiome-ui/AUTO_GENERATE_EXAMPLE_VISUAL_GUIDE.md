# Auto-Generate Example Button - Visual Guide

## Button Location

The generate example button appears in the upper right corner of the Example field:

```
┌─────────────────────────────────────────────────────────┐
│ Example                                         ✨      │
│ ┌───────────────────────────────────────────────────┐   │
│ │                                                   │   │
│ │  (JSON example value text area)                  │   │
│ │                                                   │   │
│ └───────────────────────────────────────────────────┘   │
│ JSON example value                                      │
└─────────────────────────────────────────────────────────┘
```

## Button Features

- **Icon:** ✨ Magic wand (AutoAwesome)
- **Color:** Blue (primary theme color)
- **Size:** Small
- **Position:** Upper right, aligned to top
- **Tooltip:** "Generate example based on property schema"

## Usage Flow

```
User opens property → Sees Example field → Hovers over ✨ icon →
Sees tooltip → Clicks icon → Example generates → User can edit
```

## Example Generation Logic

```
┌─────────────────────────────────────────────┐
│           Property Schema                    │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│     Check for Enum Values?                   │
│     ┌────────┐         ┌────────┐            │
│     │  Yes   │────────▶│ Use 1st│            │
│     └────────┘         │  enum  │            │
│     ┌────────┐         └────────┘            │
│     │   No   │                                │
│     └────┬───┘                                │
└──────────┼──────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│        Check Base Type                       │
├──────────────────────────────────────────────┤
│  string  → Check format/pattern              │
│  number  → Use min/max or 42.5               │
│  integer → Use min/max or 42                 │
│  boolean → true                              │
│  object  → Build with nested props           │
│  array   → Empty array []                    │
│  ref     → { id: 1, name: "example" }        │
└──────────┬───────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│      Is Array Type?                          │
│      ┌────────┐         ┌────────┐           │
│      │  Yes   │────────▶│ Wrap   │           │
│      └────────┘         │in [ ]  │           │
│      ┌────────┐         └────────┘           │
│      │   No   │                               │
│      └────┬───┘                               │
└───────────┼──────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────┐
│    Convert to JSON string (formatted)        │
│    JSON.stringify(value, null, 2)            │
└──────────┬───────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│    Populate Example Field                    │
└──────────────────────────────────────────────┘
```

## Format-Specific Examples

| Format      | Generated Example                        |
|-------------|------------------------------------------|
| email       | "user@example.com"                       |
| uri/url     | "https://example.com"                    |
| date        | "2025-11-30"                             |
| date-time   | "2025-11-30T12:00:00Z"                   |
| time        | "12:00:00"                               |
| uuid        | "123e4567-e89b-12d3-a456-426614174000"   |
| pattern     | "string matching pattern: {pattern}"     |
| (none)      | Uses description or "example string"     |

## Smart Constraint Handling

### Number with Min/Max
```javascript
// Property: { type: "number", minimum: 10, maximum: 100 }
// Generated: 10
```

### Integer with Exclusive Bounds
```javascript
// Property: { type: "integer", minimum: 0, exclusiveMinimum: true }
// Generated: 1
```

### String with Pattern
```javascript
// Property: { type: "string", pattern: "^[A-Z]{3}$" }
// Generated: "string matching pattern: ^[A-Z]{3}$"
```

### Object with Nested Properties
```javascript
// Property: { type: "object" } with nested:
//   - firstName: string
//   - age: number
//   - active: boolean
// Generated:
{
  "firstName": "example",
  "age": 0,
  "active": true
}
```

## Code Structure

```typescript
// Component hierarchy
PropertyFormFields
  └─ TextField (Example field)
      └─ InputProps
          └─ endAdornment
              └─ InputAdornment
                  └─ Tooltip
                      └─ IconButton
                          └─ AutoAwesomeIcon
                              onClick={generateExample}
```

## Integration Points

1. **Input:** Receives property schema from parent component
   - `baseType`: string, number, integer, boolean, object, array
   - `isArray`: boolean flag for array types
   - `data`: PropertyFormData with all constraints
   - `nestedProperties`: For object types with children

2. **Processing:** Analyzes schema and generates appropriate example

3. **Output:** Calls `onChange('example', jsonString)` to update form

4. **User Interaction:** User can click button anytime to regenerate

