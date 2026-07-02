# Additional Properties Field Support

## Date: November 12, 2025

## Overview

Added support for editing the `additionalProperties` field in object-type properties. This JSON Schema field controls whether objects can have properties beyond those explicitly defined in the schema.

## What is additionalProperties?

The `additionalProperties` field is a JSON Schema keyword that controls validation of properties not explicitly defined in the schema:

- **Default (not set)**: JSON Schema default behavior - additional properties are allowed
- **`true`**: Explicitly allow any additional properties (same as default, but explicit)
- **`false`**: Strict schema - only properties explicitly defined are allowed
- **Object schema**: Additional properties must conform to the specified schema (not currently supported in UI)

## Use Cases

### 1. Strict Schema Validation
```json
{
  "User": {
    "type": "object",
    "properties": {
      "id": { "type": "string" },
      "name": { "type": "string" }
    },
    "additionalProperties": false
  }
}
```
**Result**: Only `id` and `name` are allowed. Any other properties will fail validation.

### 2. Flexible Schema (Default)
```json
{
  "Config": {
    "type": "object",
    "properties": {
      "version": { "type": "string" }
    }
  }
}
```
**Result**: The `version` property is defined, but additional properties are allowed.

### 3. Explicit Allow
```json
{
  "Metadata": {
    "type": "object",
    "properties": {
      "created": { "type": "string" }
    },
    "additionalProperties": true
  }
}
```
**Result**: Same as default, but explicitly states that additional properties are allowed.

## Implementation

### File Modified

**`/apiome-ui/src/app/components/ade/studio/ClassPropertyEditDialog.tsx`**

### Changes Made

#### 1. New State Variable
```typescript
const [editPropAdditionalProperties, setEditPropAdditionalProperties] = 
  useState<'default' | 'true' | 'false'>('default');
```

#### 2. State Initialization
```typescript
// Handle additionalProperties - only relevant for object types
if (propData.hasOwnProperty('additionalProperties')) {
  setEditPropAdditionalProperties(propData.additionalProperties === false ? 'false' : 'true');
} else {
  setEditPropAdditionalProperties('default');
}
```

#### 3. Save Handler Update
```typescript
// Handle additionalProperties field
if (editPropAdditionalProperties === 'true') {
  updatedData.additionalProperties = true;
} else if (editPropAdditionalProperties === 'false') {
  updatedData.additionalProperties = false;
} else {
  // 'default' - remove the field to use JSON Schema default behavior
  delete updatedData.additionalProperties;
}
```

#### 4. UI Controls (Conditional)
Only shown for object-type properties (type: "object" without $ref):
- **Default** checkbox - Use JSON Schema default behavior
- **Allow Additional** checkbox - Explicitly allow (additionalProperties: true)
- **Strict Schema** checkbox - Disallow additional properties (additionalProperties: false)

## UI Display

### For Object-Type Properties

When editing an object-type property, the dialog now shows:

```
┌─────────────────────────────────────────────┐
│ Edit Property in Class                      │
├─────────────────────────────────────────────┤
│ Property Name: address                      │
│ Description: User address object            │
│                                             │
│ OpenAPI 3.1.0 Extensions                    │
│ ☐ Required                                  │
│ ☐ Deprecated                                │
│ ☐ Read Only                                 │
│ ☐ Write Only                                │
│                                             │
│ Object Schema Settings                      │
│ Additional Properties                       │
│   ☑ Default - Use JSON Schema default      │
│   ☐ Allow Additional - Explicitly allow    │
│   ☐ Strict Schema - Only defined props     │
│                                             │
│ Example Value: [text field]                │
│                                             │
│           [Cancel]  [Save]                  │
└─────────────────────────────────────────────┘
```

### For Non-Object Properties

For string, number, boolean, array, or $ref properties, the "Object Schema Settings" section is **not shown** since `additionalProperties` only applies to object types.

## Behavior

### Three Options

1. **Default (Recommended)**
   - Field is not set in the schema
   - Uses JSON Schema default behavior
   - Additional properties are implicitly allowed
   - Most flexible option

2. **Allow Additional**
   - Sets `"additionalProperties": true`
   - Explicitly documents that additional properties are allowed
   - Same behavior as default, but explicit
   - Good for documentation clarity

3. **Strict Schema**
   - Sets `"additionalProperties": false`
   - Only defined properties are valid
   - Additional properties will fail validation
   - Use for strict API contracts

### Radio Button Behavior

The three options are mutually exclusive (only one can be selected at a time):
- Clicking one option automatically deselects the others
- The selected option is visually indicated with a checked checkbox

## OpenAPI Generation

The `additionalProperties` field is automatically included in the generated OpenAPI schema:

### Example 1: Strict Schema
```typescript
// Property data in database:
{
  type: "object",
  additionalProperties: false,
  properties: {
    street: { type: "string" },
    city: { type: "string" }
  }
}

// Generated OpenAPI:
{
  "address": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "street": { "type": "string" },
      "city": { "type": "string" }
    }
  }
}
```

### Example 2: Default (Field Not Set)
```typescript
// Property data in database:
{
  type: "object",
  properties: {
    street: { type: "string" }
  }
}

// Generated OpenAPI:
{
  "address": {
    "type": "object",
    "properties": {
      "street": { "type": "string" }
    }
  }
}
// Note: additionalProperties not present, uses JSON Schema default
```

## Use Case Examples

### Example 1: Strict User Model
```
Scenario: User management API with strict validation
Requirement: Only allow defined user properties

Solution:
1. Create "User" class with properties: id, name, email
2. Edit each property
3. For the User class schema itself, would set additionalProperties: false
4. This ensures no unexpected properties in user objects
```

### Example 2: Flexible Configuration Object
```
Scenario: Application configuration that may have custom fields
Requirement: Allow defined fields plus any custom configuration

Solution:
1. Create property "config" (type: object)
2. Add defined properties: version, environment
3. Set additionalProperties to "Default" or "Allow Additional"
4. Custom configuration fields can be added by users
```

### Example 3: Address with Nested Strict Object
```
Scenario: Address object with strict structure
Requirement: Only standard address fields allowed

Solution:
1. Create property "address" (type: object)
2. Add nested properties: street, city, state, zipCode
3. Edit "address" property
4. Set additionalProperties to "Strict Schema"
5. Only the four defined fields are valid
```

## Integration with Nested Properties

The `additionalProperties` field works seamlessly with nested properties:

```json
{
  "User": {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "address": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "street": { "type": "string" },
          "city": { "type": "string" }
        }
      }
    }
  }
}
```

In this example:
- The User class can have additional properties (default behavior)
- The address object is strict (only street and city allowed)

## Validation Impact

### With additionalProperties: false

**Valid:**
```json
{
  "street": "123 Main St",
  "city": "Springfield"
}
```

**Invalid:**
```json
{
  "street": "123 Main St",
  "city": "Springfield",
  "country": "USA"  // ❌ Not defined in schema
}
```

### With additionalProperties: true (or default)

**Valid:**
```json
{
  "street": "123 Main St",
  "city": "Springfield",
  "country": "USA"  // ✅ Additional properties allowed
}
```

## Benefits

1. **Strict Validation**: Enforce exact schema compliance when needed
2. **Flexibility**: Allow extensibility when appropriate
3. **Documentation**: Explicitly communicate schema expectations
4. **API Contracts**: Clearly define what properties are allowed
5. **Validation**: Prevent unexpected data in strict scenarios

## Best Practices

### When to Use Strict (false)

- ✅ Database models with fixed schemas
- ✅ API request/response bodies with strict contracts
- ✅ Configuration objects with known fields
- ✅ Security-sensitive objects
- ✅ When you want to catch typos or unexpected fields

### When to Use Flexible (default/true)

- ✅ Extension points in your API
- ✅ User-defined metadata
- ✅ Configuration with custom settings
- ✅ Objects that may evolve over time
- ✅ When backward compatibility is important

### Recommendations

1. **Start Flexible**: Begin with default/allow, add strict later if needed
2. **Document Intent**: Use "Allow Additional" to explicitly document flexibility
3. **Use Strict Carefully**: Only use when you truly need strict validation
4. **Consider Evolution**: Strict schemas are harder to extend later
5. **Test Validation**: Verify your schema validation works as expected

## Testing

### Manual Testing Checklist

- [ ] Create object-type property
- [ ] Edit property and verify "Object Schema Settings" section appears
- [ ] Select "Default" option
- [ ] Save and verify `additionalProperties` not in schema
- [ ] Edit again, select "Allow Additional"
- [ ] Save and verify `"additionalProperties": true` in schema
- [ ] Edit again, select "Strict Schema"
- [ ] Save and verify `"additionalProperties": false` in schema
- [ ] Edit non-object property (string, number, etc.)
- [ ] Verify "Object Schema Settings" section does NOT appear
- [ ] Test with nested properties
- [ ] Generate OpenAPI spec and verify field appears correctly
- [ ] Test in Swagger UI

## Backward Compatibility

✅ **Fully Backward Compatible**

- Existing properties without `additionalProperties` field continue to work
- Default behavior unchanged (allows additional properties)
- Only affects properties where user explicitly sets the field
- No database migration required

## Known Limitations

1. **Schema Objects**: Currently only supports boolean values (true/false). Does not support object schemas for additionalProperties.
2. **Class-Level Setting**: This affects individual properties. For class-level schema settings, would need separate implementation.
3. **UI Validation**: The UI doesn't validate against the additionalProperties setting - it only generates the schema.

## Future Enhancements

### 1. Schema Objects for additionalProperties
```json
{
  "metadata": {
    "type": "object",
    "additionalProperties": {
      "type": "string"
    }
  }
}
```
Would allow any additional properties, but they must be strings.

### 2. Class-Level Setting
Allow setting `additionalProperties` on the class schema itself, not just individual properties.

### 3. Validation Preview
Show examples of valid/invalid objects based on the setting.

### 4. Import/Export
Ensure OpenAPI import properly handles `additionalProperties` field.

## Related Documentation

- [Nested Properties UI Feature](./NESTED_PROPERTIES_UI_FEATURE.md)
- [OpenAPI Generation](./OPENAPI_NESTED_PROPERTIES.md)
- [JSON Schema Specification](https://json-schema.org/understanding-json-schema/reference/object.html#additional-properties)

## Summary

✅ **Feature Complete**

The `additionalProperties` field is now fully supported for object-type properties:
- ✅ UI controls in edit dialog
- ✅ Three options: Default, Allow Additional, Strict Schema
- ✅ Only shown for relevant property types
- ✅ Properly saved to database
- ✅ Included in OpenAPI generation
- ✅ Works with nested properties
- ✅ Fully backward compatible

Users can now control whether object-type properties allow additional fields beyond those explicitly defined, enabling both strict and flexible schema validation as needed.

---

**Implementation Status:** ✅ Complete  
**Backward Compatible:** ✅ Yes  
**Breaking Changes:** ❌ None  
**Testing Status:** ⏳ Ready for Manual Testing

