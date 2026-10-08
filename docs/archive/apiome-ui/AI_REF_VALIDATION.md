# AI $ref Validation - Ticket #818

## Issue Description
The AI was sometimes hallucinating incorrect $ref structures that referenced individual properties within schemas instead of referencing complete schemas. This violates OpenAPI/JSON Schema specifications where $ref must point to complete schema definitions.

## Problem Examples

### ❌ INCORRECT Usage (Hallucinated)
```json
{
  "properties": {
    "userEmail": {
      "$ref": "#/components/schemas/User/properties/email"
    },
    "userName": {
      "$ref": "#/components/schemas/User#/properties/name"
    }
  }
}
```

### ✅ CORRECT Usage
```json
{
  "properties": {
    "user": {
      "$ref": "#/components/schemas/User"
    }
  }
}
```

If you need to reference a specific type, create a separate schema:
```json
{
  "components": {
    "schemas": {
      "Email": {
        "type": "string",
        "format": "email"
      },
      "User": {
        "type": "object",
        "properties": {
          "email": {
            "$ref": "#/components/schemas/Email"
          },
          "name": {
            "type": "string"
          }
        }
      }
    }
  }
}
```

## Solution Implemented

### Changes to `/src/app/api/ollama/chat/route.ts`

Added explicit instructions in the system prompt to prevent property-level $ref hallucinations:

1. **In Rules Section:**
```
- **CRITICAL: $ref must ONLY reference complete schemas in #/components/schemas, NEVER individual properties within a schema**
- **CORRECT: { "$ref": "#/components/schemas/User" }**
- **INCORRECT: { "$ref": "#/components/schemas/User/properties/email" }**
- **INCORRECT: { "$ref": "#/components/schemas/User#/properties/email" }**
- When you need to reference a class/schema, use: "#/components/schemas/ClassName"
```

2. **In Generation Instructions Section:**
```
- **$ref MUST reference complete schemas only**: Use "#/components/schemas/ClassName" format
- **NEVER use $ref to reference properties**: Do not use "#/components/schemas/ClassName/properties/propertyName" or similar patterns
```

## Valid $ref Patterns

### ✅ Direct Schema Reference
```json
{
  "$ref": "#/components/schemas/User"
}
```

### ✅ Composition with allOf
```json
{
  "allOf": [
    { "$ref": "#/components/schemas/User" },
    { "$ref": "#/components/schemas/Admin" }
  ]
}
```

### ✅ Union with anyOf
```json
{
  "anyOf": [
    { "$ref": "#/components/schemas/Email" },
    { "$ref": "#/components/schemas/Phone" }
  ]
}
```

### ✅ Exclusive Choice with oneOf
```json
{
  "oneOf": [
    { "$ref": "#/components/schemas/CreditCard" },
    { "$ref": "#/components/schemas/BankTransfer" }
  ]
}
```

### ✅ Array of References
```json
{
  "type": "array",
  "items": {
    "$ref": "#/components/schemas/Product"
  }
}
```

## Testing the Fix

### Test Prompts

Try these prompts to verify the AI doesn't generate invalid $ref patterns:

1. **"Create a User class with an email property that should be reusable"**
   - Expected: Separate Email schema with $ref to Email, not to User's email property

2. **"Generate an Order schema that references user information"**
   - Expected: $ref to User schema, not to individual User properties

3. **"Create a Blog Post with author information"**
   - Expected: $ref to Author/User schema, not to User.name or User.email

4. **"Make a Product schema with pricing information that can be reused"**
   - Expected: Separate Price schema if needed, not $ref to Product/properties/price

### Validation Checks

After generation, verify:
- [ ] All $ref values match pattern: `#/components/schemas/[ClassName]`
- [ ] No $ref values contain `/properties/` in the path
- [ ] No $ref values use fragment identifier for properties (e.g., `#/properties/`)
- [ ] Referenced schemas exist in components/schemas section

## Related Documentation

- OpenAPI 3.1.0 Specification: https://spec.openapis.org/oas/v3.1.0
- JSON Schema $ref specification: https://json-schema.org/understanding-json-schema/structuring.html#ref
- [PROPERTY_COMPOSITION_IMPLEMENTATION_SUMMARY.md](./PROPERTY_COMPOSITION_IMPLEMENTATION_SUMMARY.md)

## Implementation Status

✅ **IMPLEMENTED** - Ticket #818
- Updated AI system prompt with explicit $ref validation rules
- Added clear examples of correct vs incorrect usage
- Reinforced in multiple sections of the prompt for emphasis
- No code changes needed in schema generation utilities (already correct)

## Future Enhancements

Consider adding:
1. Post-generation validation to catch any $ref violations
2. Automatic schema extraction for commonly reused property patterns
3. User-facing warnings if invalid $ref patterns are detected
4. Schema linting that flags invalid $ref patterns before import
