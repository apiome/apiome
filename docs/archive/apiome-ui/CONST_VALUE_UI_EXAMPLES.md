# Constant Value Feature - UI Examples

## Property Form with Const Value

When editing a property, the Constant Value field appears in the Constraints section:

```
┌─────────────────────────────────────────────────────────────┐
│ Standard Fields              │  Constraints                 │
├─────────────────────────────────────────────────────────────┤
│                              │                              │
│ Title                        │  Constant Value              │
│ [________________]           │  [active_________________]   │
│                              │  Use const when a property   │
│ Description                  │  should only have one value  │
│ [________________]           │                              │
│ [________________]           │  ┌────────────────────────┐  │
│                              │  │ ℹ️ Constant Value Set  │  │
│ Default Value                │  │                        │  │
│ [________________]           │  │ This property will     │  │
│                              │  │ only accept the value: │  │
│ ☐ Required                   │  │ active                 │  │
│ ☐ Read Only                  │  │                        │  │
│ ☐ Write Only                 │  │ Useful for            │  │
│ ☐ Deprecated                 │  │ discriminator fields  │  │
│                              │  │ or fixed config.      │  │
│                              │  └────────────────────────┘  │
│                              │                              │
│                              │  Allowed Values (Enum)       │
│                              │  ⚠️ Constant value is set -  │
│                              │     enum is disabled         │
│                              │                              │
│                              │  [Add Enum Value_________] ⊕ │
│                              │  (Disabled)                  │
└─────────────────────────────────────────────────────────────┘
```

## Property Form with Enum Values

When enum values are set, const is disabled:

```
┌─────────────────────────────────────────────────────────────┐
│ Standard Fields              │  Constraints                 │
├─────────────────────────────────────────────────────────────┤
│                              │                              │
│ Title                        │  Constant Value              │
│ [________________]           │  [_____________________]     │
│                              │  (Disabled when enum is set) │
│ Description                  │                              │
│ [Status field____]           │  Allowed Values (Enum)  ⬍ ⬍ │
│ [________________]           │  Enum values apply to each   │
│                              │  item in the array           │
│ Default Value                │                              │
│ [________________]           │  [Add Enum Value_________] ⊕ │
│                              │  Enter a string value        │
│ ☑ Required                   │                              │
│ ☐ Read Only                  │  ╔════════════════════════╗  │
│ ☐ Write Only                 │  ║ ☰ active          ✕    ║  │
│ ☐ Deprecated                 │  ║ ☰ pending         ✕    ║  │
│                              │  ║ ☰ inactive        ✕    ║  │
│                              │  ║ ☰ cancelled       ✕    ║  │
│                              │  ╚════════════════════════╝  │
└─────────────────────────────────────────────────────────────┘
```

## Different Type Examples

### String Constant
```
Property: objectType
Type: string
Const: "User"
Description: "Object type discriminator"

JSON Schema:
{
  "type": "string",
  "const": "User",
  "description": "Object type discriminator"
}
```

### Integer Constant
```
Property: maxRetries
Type: integer
Const: 3
Description: "Maximum number of retry attempts"

JSON Schema:
{
  "type": "integer",
  "const": 3,
  "description": "Maximum number of retry attempts"
}
```

### Boolean Constant
```
Property: isActive
Type: boolean
Const: true
Description: "Feature is always active"

JSON Schema:
{
  "type": "boolean",
  "const": true,
  "description": "Feature is always active"
}
```

### Array with Constant Items
```
Property: tags
Type: array
Items Type: string
Items Const: "user"
Description: "Array of user tags"

JSON Schema:
{
  "type": "array",
  "items": {
    "type": "string",
    "const": "user"
  },
  "description": "Array of user tags"
}
```

## Class Node Display

Properties with const values appear in the class node like any other property:

```
┌────────────────────────────────┐
│ User                      🗑️   │
├────────────────────────────────┤
│ User entity                    │
├────────────────────────────────┤
│ ▾  * objectType      string    │
│ ▾  * id              string    │
│ ▾    name            string    │
│ ▾    email           string    │
│ ▾    status          string    │
└────────────────────────────────┘

When editing objectType property:
- Name: objectType
- Type: string
- Required: ✓
- Const: "User"
- Description: "Discriminator field"
```

## Use Cases in Action

### 1. Polymorphic Objects with Discriminators

**Base Schema**: Animal
```json
{
  "oneOf": [
    { "$ref": "#/components/schemas/Dog" },
    { "$ref": "#/components/schemas/Cat" }
  ],
  "discriminator": {
    "propertyName": "animalType"
  }
}
```

**Dog Schema**:
```json
{
  "type": "object",
  "properties": {
    "animalType": {
      "type": "string",
      "const": "dog"
    },
    "breed": { "type": "string" },
    "goodBoy": { "type": "boolean" }
  }
}
```

**Cat Schema**:
```json
{
  "type": "object",
  "properties": {
    "animalType": {
      "type": "string",
      "const": "cat"
    },
    "breed": { "type": "string" },
    "livesRemaining": { "type": "integer" }
  }
}
```

### 2. API Versioning

**Request Object**:
```json
{
  "type": "object",
  "properties": {
    "apiVersion": {
      "type": "string",
      "const": "v2",
      "description": "API version identifier"
    },
    "data": {
      "type": "object"
    }
  }
}
```

### 3. Feature Flags

**Configuration Object**:
```json
{
  "type": "object",
  "properties": {
    "featureEnabled": {
      "type": "boolean",
      "const": true,
      "description": "Feature is always enabled in this environment"
    },
    "maxConcurrency": {
      "type": "integer",
      "const": 10,
      "description": "Fixed concurrency limit"
    }
  }
}
```

## Validation Behavior

When a property has a const value, API validation will:

✅ **Accept**: Request with matching const value
```json
{ "objectType": "User" }
```

❌ **Reject**: Request with different value
```json
{ "objectType": "Admin" }
```
Error: "Property 'objectType' must have value 'User'"

❌ **Reject**: Request with missing const property (if required)
```json
{ "name": "John" }
```
Error: "Required property 'objectType' is missing"

## Migration Path

If you have existing properties with single-item enums that should be const:

**Before (single-item enum)**:
```json
{
  "type": "string",
  "enum": ["active"]
}
```

**After (const)**:
```json
{
  "type": "string",
  "const": "active"
}
```

To migrate:
1. Open the property editor
2. Remove the single enum value
3. Set the const field to the same value
4. Save the property

Both are functionally equivalent, but const is more semantically correct.

