# Nested Properties - Quick Reference Guide

## What are Nested Properties?

Nested properties allow you to define inline object structures by adding properties as children of other properties. This is useful for creating complex data models without creating separate classes.

## How to Create Nested Properties

### Step 1: Create an Object Property

1. Click "New Property" in the sidebar
2. Set the name (e.g., "address")
3. Set the type to "object"
4. Save the property

### Step 2: Add the Property to a Class

1. Drag the object property from the sidebar
2. Drop it onto the class node on the canvas
3. The property appears in the class

### Step 3: Add Child Properties

1. Create a new property (e.g., "street" with type "string")
2. Drag the new property from the sidebar
3. **Drop it directly onto the object property** (not the class header)
4. The property becomes a child of the object property

### Step 4: Expand to View

1. Click the chevron icon (▶) next to the object property
2. The chevron rotates to (▼) and shows all child properties
3. Click again to collapse

## Visual Guide

```
┌─────────────────────────────────────┐
│ User                           [×]  │  ← Class Header
├─────────────────────────────────────┤
│  ▼ address      object    [✎] [×] │  ← Object Property (expanded)
│    └── street   string    [✎] [×] │  ← Child Property (indented)
│    └── city     string    [✎] [×] │  ← Child Property (indented)
│    └── zipCode  string    [✎] [×] │  ← Child Property (indented)
│  name            string    [✎] [×] │  ← Top-level Property
│  email           string    [✎] [×] │  ← Top-level Property
└─────────────────────────────────────┘
```

## Visual Indicators

| Indicator | Meaning |
|-----------|---------|
| **▶** | Object property (collapsed) - has or can have children |
| **▼** | Object property (expanded) - showing children |
| **(3)** | Number of child properties |
| Indented | Nested property (child of another property) |
| Green highlight | Valid drop zone when dragging |

## Common Use Cases

### 1. Address Information

```
address (object)
├── street (string)
├── city (string)
├── state (string)
└── zipCode (string)
```

### 2. Nested Configuration

```
config (object)
├── database (object)
│   ├── host (string)
│   ├── port (number)
│   └── name (string)
└── api (object)
    ├── baseUrl (string)
    └── timeout (number)
```

### 3. Metadata Object

```
metadata (object)
├── created (string, format: date-time)
├── updated (string, format: date-time)
└── version (number)
```

## Tips and Tricks

### ✅ DO

- Use nested properties for closely related data that belongs together
- Keep nesting levels reasonable (2-3 levels is usually sufficient)
- Name parent objects descriptively (e.g., "address", "settings", "config")
- Use object properties when you don't need to reuse the structure

### ❌ DON'T

- Don't nest too deeply (5+ levels becomes hard to manage)
- Don't use nested properties when the structure should be reusable
- Don't create circular references (parent referencing child referencing parent)
- Don't forget to expand to see your nested properties!

## When to Use Nested Properties vs. Separate Classes

### Use Nested Properties When:
- The structure is specific to one class
- The structure is simple and won't be reused
- You want to keep related data together
- The data is truly a "part-of" relationship

### Use Separate Classes When:
- The structure will be used by multiple classes
- The structure is complex (10+ properties)
- The structure represents an independent concept
- You need to create relationships between classes

## Example Workflow

**Scenario**: Create a User class with an embedded address

1. **Create the User class**
   - Name: "User"
   - Description: "Application user"

2. **Add basic properties**
   - Drag "name" (string) to User class
   - Drag "email" (string) to User class

3. **Create address object**
   - Create property "address" (object)
   - Drag to User class

4. **Add address fields**
   - Create property "street" (string)
   - Drag to "address" property (not the class!)
   - Create property "city" (string)
   - Drag to "address" property
   - Create property "zipCode" (string)
   - Drag to "address" property

5. **View the result**
   - Click chevron next to "address"
   - See all nested properties
   - The address object now has inline properties!

## Keyboard Shortcuts

Currently, nested properties use mouse interactions. Consider these patterns:

- **Click chevron**: Toggle expand/collapse
- **Drag property**: Add to parent
- **Click edit button**: Edit property details
- **Click delete button**: Remove property

## Troubleshooting

### Property won't drop on object property
- ✓ Ensure the property is type "object"
- ✓ Check you're not in read-only mode
- ✓ Make sure you're dropping on the property row, not the class header

### Can't see child properties
- ✓ Click the chevron icon to expand
- ✓ Verify the parent property is type "object"
- ✓ Check that child properties were added successfully (refresh if needed)

### Property appears at wrong level
- ✓ Ensure you dropped on the correct parent property
- ✓ Check the indentation - it should be 16px per level
- ✓ You can delete and re-add if it's in the wrong place

### Green highlight doesn't appear
- ✓ The property must be type "object" to accept drops
- ✓ You must be in edit mode (not read-only)
- ✓ Try dragging slower over the target property

## API Representation

Nested properties are represented in OpenAPI/JSON Schema as:

```json
{
  "User": {
    "type": "object",
    "properties": {
      "name": {
        "type": "string"
      },
      "email": {
        "type": "string"
      },
      "address": {
        "type": "object",
        "properties": {
          "street": { "type": "string" },
          "city": { "type": "string" },
          "zipCode": { "type": "string" }
        }
      }
    }
  }
}
```

## Additional Resources

- [Full Feature Documentation](./NESTED_PROPERTIES_UI_FEATURE.md)
- [Database Schema Documentation](../../apiome-db/docs/NESTED_PROPERTIES_FEATURE.md)
- [API Documentation](../../apiome-rest/docs/README.md)

## Need Help?

If you encounter issues or have questions about nested properties, please refer to the full documentation or contact support.

