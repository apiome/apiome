# Test Cases for anyOf Property Support in Mermaid

## Test Case 1: Basic anyOf with Class References

**Input Property Data:**
```json
{
  "name": "payment_method",
  "data": {
    "anyOf": [
      { "$ref": "#/components/schemas/CreditCard" },
      { "$ref": "#/components/schemas/BankAccount" },
      { "$ref": "#/components/schemas/PayPal" }
    ]
  }
}
```

**Expected Mermaid Output:**
```mermaid
class Order {
    +CreditCard | BankAccount | PayPal payment_method
}
Order ..> CreditCard : payment_method[anyOf-0]
Order ..> BankAccount : payment_method[anyOf-1]
Order ..> PayPal : payment_method[anyOf-2]
```

---

## Test Case 2: anyOf with Primitive Types

**Input Property Data:**
```json
{
  "name": "identifier",
  "data": {
    "anyOf": [
      { "type": "string" },
      { "type": "number" }
    ]
  }
}
```

**Expected Mermaid Output:**
```mermaid
class Product {
    +string | number identifier
}
```
*(No relationship lines for primitive types)*

---

## Test Case 3: anyOf in Array Items

**Input Property Data:**
```json
{
  "name": "participants",
  "data": {
    "type": "array",
    "items": {
      "anyOf": [
        { "$ref": "#/components/schemas/User" },
        { "$ref": "#/components/schemas/Organization" }
      ]
    }
  }
}
```

**Expected Mermaid Output:**
```mermaid
class Event {
    +(User | Organization)[] participants
}
Event ..> User : participants[anyOf-0]
Event ..> Organization : participants[anyOf-1]
```

---

## Test Case 4: oneOf with Class References

**Input Property Data:**
```json
{
  "name": "content",
  "data": {
    "oneOf": [
      { "$ref": "#/components/schemas/TextContent" },
      { "$ref": "#/components/schemas/VideoContent" },
      { "$ref": "#/components/schemas/ImageContent" }
    ]
  }
}
```

**Expected Mermaid Output:**
```mermaid
class Post {
    +TextContent | VideoContent | ImageContent content
}
Post ..> TextContent : content[oneOf-0]
Post ..> VideoContent : content[oneOf-1]
Post ..> ImageContent : content[oneOf-2]
```

---

## Test Case 5: allOf with Class References

**Input Property Data:**
```json
{
  "name": "entity",
  "data": {
    "allOf": [
      { "$ref": "#/components/schemas/BaseEntity" },
      { "$ref": "#/components/schemas/Auditable" }
    ]
  }
}
```

**Expected Mermaid Output:**
```mermaid
class Document {
    +BaseEntity & Auditable entity
}
Document ..> BaseEntity : entity[allOf-0]
Document ..> Auditable : entity[allOf-1]
```

---

## Test Case 6: Mixed anyOf (References + Primitives)

**Input Property Data:**
```json
{
  "name": "value",
  "data": {
    "anyOf": [
      { "type": "string" },
      { "type": "number" },
      { "$ref": "#/components/schemas/ComplexValue" }
    ]
  }
}
```

**Expected Mermaid Output:**
```mermaid
class Configuration {
    +string | number | ComplexValue value
}
Configuration ..> ComplexValue : value[anyOf-2]
```
*(Only ComplexValue gets a relationship line)*

---

## Test Case 7: Nested Array with oneOf

**Input Property Data:**
```json
{
  "name": "attachments",
  "data": {
    "type": "array",
    "items": {
      "oneOf": [
        { "$ref": "#/components/schemas/File" },
        { "$ref": "#/components/schemas/Link" }
      ]
    }
  }
}
```

**Expected Mermaid Output:**
```mermaid
class Message {
    +(File | Link)[] attachments
}
Message ..> File : attachments[oneOf-0]
Message ..> Link : attachments[oneOf-1]
```

---

## Test Case 8: Class with Multiple anyOf Properties

**Input:**
```json
{
  "name": "Invoice",
  "properties": [
    {
      "name": "customer",
      "data": {
        "anyOf": [
          { "$ref": "#/components/schemas/Individual" },
          { "$ref": "#/components/schemas/Company" }
        ]
      }
    },
    {
      "name": "payment",
      "data": {
        "anyOf": [
          { "$ref": "#/components/schemas/Cash" },
          { "$ref": "#/components/schemas/Card" }
        ]
      }
    }
  ]
}
```

**Expected Mermaid Output:**
```mermaid
class Invoice {
    +Individual | Company customer
    +Cash | Card payment
}
Invoice ..> Individual : customer[anyOf-0]
Invoice ..> Company : customer[anyOf-1]
Invoice ..> Cash : payment[anyOf-0]
Invoice ..> Card : payment[anyOf-1]
```

---

## Verification Checklist

- [ ] anyOf with class references shows union type notation
- [ ] anyOf with primitive types shows type union
- [ ] anyOf creates dashed relationship lines (..>)
- [ ] Each anyOf option is indexed [anyOf-N]
- [ ] oneOf behaves same as anyOf but labeled as oneOf
- [ ] allOf uses intersection operator (&)
- [ ] Array items with anyOf show (Type1 | Type2)[] notation
- [ ] Mixed anyOf (refs + primitives) only creates relationships for refs
- [ ] Multiple anyOf properties in same class all work correctly
- [ ] Backward compatibility: simple $ref properties still work

---

## How to Test

1. Create a new project in the Studio
2. Create classes matching the test cases above
3. Add properties with anyOf/oneOf/allOf as specified
4. Switch to Mermaid view
5. Verify the property types display correctly
6. Verify the relationship lines are generated correctly
7. Copy the Mermaid code and render it in a Mermaid-compatible tool
8. Confirm the diagram renders without errors

---

## Notes

- Mermaid syntax uses `..>` for dependencies/dashed relationships
- Union types use `|` separator (standard TypeScript notation)
- Intersection types use `&` separator (standard TypeScript notation)
- Index labels [anyOf-N] help distinguish multiple alternatives
- Property names are preserved in relationship labels

