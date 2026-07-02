# Discriminator Configuration Feature

## Overview
Enhanced the discriminator functionality for classes using oneOf, anyOf, or allOf compositions. The discriminator helps code generators and documentation tools understand polymorphic types by specifying which property distinguishes between schema variants.

## Implementation Date
December 13, 2025

## Feature Description
When using composition patterns (oneOf, anyOf, allOf), users can now:
1. Specify a discriminator property name (e.g., "type", "kind", "petType")
2. Choose between automatic or explicit mapping
3. Define custom property value to schema mappings (e.g., "dog" → Dog, "cat" → Cat)
4. Get validation warnings for unmapped schemas

This is especially important for oneOf where exactly one schema must match.

## Changes Made

### ClassEditDialog Component
**File:** `/src/app/components/ade/studio/ClassEditDialog.tsx`

#### State Changes:
- Added `discriminatorMapping: Record<string, string>` to formData
  - Maps property values to schema names
  - Example: `{ "dog": "Dog", "cat": "Cat", "bird": "Bird" }`

#### UI Enhancements:

**Before:**
- Simple text field for discriminator property name
- Checkbox for "Use automatic mapping"
- No visibility into what mapping means
- No way to customize mapping values

**After:**
- Improved section title: "Discriminator Configuration"
- Contextual help text explaining purpose and importance
- Text field for discriminator property name
- Checkbox with clearer label: "Use automatic mapping (implicit mapping based on schema names)"
- **NEW:** Explicit mapping editor when automatic mapping is disabled
  - Shows all schemas from composition
  - Input fields for each property value
  - Visual arrow (→) showing value-to-schema mapping
  - Schema names displayed in highlighted boxes
  - Real-time validation warnings for unmapped schemas

#### Data Flow:

**Loading (Edit Mode):**
```typescript
// Extract discriminator mapping from schema
const discriminatorMapping: Record<string, string> = {};
if (schema.discriminator?.mapping) {
  Object.entries(schema.discriminator.mapping).forEach(([key, value]) => {
    const schemaName = typeof value === 'string' ? value.split('/').pop() || '' : '';
    if (schemaName) {
      discriminatorMapping[key] = schemaName;
    }
  });
}
```

**Saving:**
```typescript
if (formData.discriminatorProperty && (formData.allOf.length > 0 || formData.anyOf.length > 0 || formData.oneOf.length > 0)) {
  schema.discriminator = { propertyName: formData.discriminatorProperty };
  if (!formData.discriminatorUseAuto && Object.keys(formData.discriminatorMapping).length > 0) {
    schema.discriminator.mapping = {};
    Object.entries(formData.discriminatorMapping).forEach(([propertyValue, schemaName]) => {
      schema.discriminator.mapping[propertyValue] = `#/components/schemas/${schemaName}`;
    });
  }
}
```

## UI/UX Details

### Discriminator Configuration Section

The section only appears when at least one composition type (allOf, anyOf, oneOf) has schemas selected.

#### Layout:
```
┌─────────────────────────────────────────────────────────────┐
│ Discriminator Configuration                                 │
│                                                              │
│ The discriminator helps code generators and documentation   │
│ tools understand polymorphic types. It's especially         │
│ important for oneOf where exactly one schema must match.    │
│                                                              │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ Discriminator Property Name                            │ │
│ │ type                                                   │ │
│ │ Property name that indicates which schema variant      │ │
│ └────────────────────────────────────────────────────────┘ │
│                                                              │
│ ☐ Use automatic mapping (implicit mapping based on          │
│   schema names)                                              │
│                                                              │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ Explicit Mapping                                       │ │
│ │                                                         │ │
│ │ Map property values to schema references.              │ │
│ │ Example: "dog" → Dog, "cat" → Cat                     │ │
│ │                                                         │ │
│ │ ┌───────────┐    →    ┌──────┐                       │ │
│ │ │ dog       │    →    │ Dog  │                       │ │
│ │ └───────────┘         └──────┘                       │ │
│ │                                                         │ │
│ │ ┌───────────┐    →    ┌──────┐                       │ │
│ │ │ cat       │    →    │ Cat  │                       │ │
│ │ └───────────┘         └──────┘                       │ │
│ │                                                         │ │
│ │ ⚠ Warning: Unmapped schemas: Bird                     │ │
│ │   These schemas won't be reachable via the             │ │
│ │   discriminator property.                              │ │
│ └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Automatic Mapping (Default)

When "Use automatic mapping" is checked:
- No explicit mapping is stored
- Code generators use implicit mapping based on schema names
- OpenAPI spec includes only `propertyName`, no `mapping` object

Example output:
```yaml
discriminator:
  propertyName: type
```

### Explicit Mapping

When "Use automatic mapping" is unchecked:
- Mapping editor appears
- Shows one row for each schema in the composition
- Left field: property value (user input)
- Right box: schema name (read-only, highlighted)
- Validation warns about unmapped schemas

Example output:
```yaml
discriminator:
  propertyName: type
  mapping:
    dog: '#/components/schemas/Dog'
    cat: '#/components/schemas/Cat'
    bird: '#/components/schemas/Bird'
```

## Use Cases

### Use Case 1: Pet API with oneOf

**Scenario:** API has a Pet base type with Dog, Cat, and Bird subtypes

**Configuration:**
- oneOf: [Dog, Cat, Bird]
- Discriminator Property: "petType"
- Explicit Mapping:
  - "canine" → Dog
  - "feline" → Cat
  - "avian" → Bird

**Result:**
```json
{
  "oneOf": [
    { "$ref": "#/components/schemas/Dog" },
    { "$ref": "#/components/schemas/Cat" },
    { "$ref": "#/components/schemas/Bird" }
  ],
  "discriminator": {
    "propertyName": "petType",
    "mapping": {
      "canine": "#/components/schemas/Dog",
      "feline": "#/components/schemas/Cat",
      "avian": "#/components/schemas/Bird"
    }
  }
}
```

### Use Case 2: Shape API with anyOf

**Scenario:** Geometric shapes that can have multiple properties

**Configuration:**
- anyOf: [Circle, Rectangle, Triangle]
- Discriminator Property: "shapeType"
- Automatic Mapping: enabled

**Result:**
```json
{
  "anyOf": [
    { "$ref": "#/components/schemas/Circle" },
    { "$ref": "#/components/schemas/Rectangle" },
    { "$ref": "#/components/schemas/Triangle" }
  ],
  "discriminator": {
    "propertyName": "shapeType"
  }
}
```

### Use Case 3: Vehicle API with Inheritance

**Scenario:** Vehicle base class with Car, Truck, Motorcycle subtypes

**Configuration:**
- allOf: [Vehicle]
- oneOf: [Car, Truck, Motorcycle]
- Discriminator Property: "vehicleKind"
- Explicit Mapping:
  - "car" → Car
  - "truck" → Truck
  - "motorcycle" → Motorcycle

**Result:**
```json
{
  "allOf": [
    { "$ref": "#/components/schemas/Vehicle" }
  ],
  "oneOf": [
    { "$ref": "#/components/schemas/Car" },
    { "$ref": "#/components/schemas/Truck" },
    { "$ref": "#/components/schemas/Motorcycle" }
  ],
  "discriminator": {
    "propertyName": "vehicleKind",
    "mapping": {
      "car": "#/components/schemas/Car",
      "truck": "#/components/schemas/Truck",
      "motorcycle": "#/components/schemas/Motorcycle"
    }
  }
}
```

## Benefits

### For Code Generators
- Know exactly which property to check for type information
- Can generate more efficient deserialization code
- Can create switch statements or pattern matching based on discriminator

### For Documentation Tools
- Can display clearer documentation about polymorphic types
- Can show which values map to which schemas
- Better user understanding of API contracts

### For API Consumers
- Clear contract about which property indicates type
- Explicit mapping makes it obvious which values are valid
- Reduces ambiguity in polymorphic APIs

### For Validation
- Can validate that discriminator property exists in all schemas
- Can check that discriminator values are unique
- Can ensure all schemas are reachable

## OpenAPI 3.1 Compliance

This implementation fully complies with OpenAPI 3.1 specification:

**From OpenAPI 3.1 Spec:**
> When using the discriminator, inline schemas will not be considered.
> The discriminator is an object name that is used to differentiate between other schemas which may satisfy the payload description.

**Required:**
- ✅ `propertyName` - name of the property that holds the discriminator value

**Optional:**
- ✅ `mapping` - maps payload values to schema names or references

**Implementation Notes:**
- Discriminator works with oneOf, anyOf, and allOf
- When using oneOf, discriminator is especially valuable for performance
- Mapping values can be different from schema names (e.g., "dog" vs "Dog")
- All referenced schemas should contain the discriminator property

## Validation and Warnings

### Unmapped Schemas Warning

When explicit mapping is enabled, the UI checks for unmapped schemas:

```typescript
const schemas = formData.oneOf.length > 0 ? formData.oneOf : 
              formData.anyOf.length > 0 ? formData.anyOf : 
              formData.allOf;
const mappedSchemas = new Set(Object.values(formData.discriminatorMapping));
const unmappedSchemas = schemas.filter(s => !mappedSchemas.has(s));
```

If unmapped schemas exist, shows warning:
```
⚠ Warning: Unmapped schemas: Bird, Fish
  These schemas won't be reachable via the discriminator property.
```

### Best Practices

1. **Use oneOf with Discriminator**: Most effective for strictly exclusive types
2. **Consistent Property**: Ensure discriminator property exists in all schemas
3. **Unique Values**: Each schema should have a unique discriminator value
4. **Meaningful Names**: Use clear, descriptive discriminator property names
5. **Document Values**: Document valid discriminator values in schema descriptions

## Migration Guide

### From Old Implementation

**Before:**
- Set discriminator property name
- Toggle "Use automatic mapping"
- Automatic mapping created entries like: `{ "Dog": "#/components/schemas/Dog" }`

**After:**
- Set discriminator property name
- Choose automatic (no mapping) or explicit
- For explicit, specify custom values: `{ "dog": "#/components/schemas/Dog" }`

**Migration:**
Existing schemas with discriminators will load correctly:
- Property name preserved
- If mapping exists, loads into discriminatorMapping
- If no mapping, discriminatorUseAuto = true

## Technical Implementation

### State Structure

```typescript
interface FormData {
  // ... other fields
  discriminatorProperty: string;
  discriminatorUseAuto: boolean;
  discriminatorMapping: Record<string, string>; // NEW
}
```

### Key Functions

**Load Mapping:**
```typescript
const discriminatorMapping: Record<string, string> = {};
if (schema.discriminator?.mapping) {
  Object.entries(schema.discriminator.mapping).forEach(([key, value]) => {
    const schemaName = typeof value === 'string' ? value.split('/').pop() || '' : '';
    if (schemaName) {
      discriminatorMapping[key] = schemaName;
    }
  });
}
```

**Save Mapping:**
```typescript
if (!formData.discriminatorUseAuto && Object.keys(formData.discriminatorMapping).length > 0) {
  schema.discriminator.mapping = {};
  Object.entries(formData.discriminatorMapping).forEach(([propertyValue, schemaName]) => {
    schema.discriminator.mapping[propertyValue] = `#/components/schemas/${schemaName}`;
  });
}
```

**Update Mapping:**
```typescript
onChange={(e) => {
  const newValue = e.target.value;
  setFormData(prev => {
    const newMapping = { ...prev.discriminatorMapping };
    
    // Remove old entry for this schema
    Object.keys(newMapping).forEach(key => {
      if (newMapping[key] === schemaName) {
        delete newMapping[key];
      }
    });
    
    // Add new entry if value is not empty
    if (newValue.trim()) {
      newMapping[newValue.trim()] = schemaName;
    }
    
    return { ...prev, discriminatorMapping: newMapping };
  });
}}
```

## Future Enhancements

Potential improvements:
1. **Validation**: Check that discriminator property exists in all schemas
2. **Auto-suggest**: Suggest discriminator property based on common patterns
3. **Value Templates**: Provide common discriminator value patterns (lowercase, snake_case, etc.)
4. **Bulk Edit**: Allow editing multiple mappings at once
5. **Import/Export**: Import mappings from JSON
6. **Schema Preview**: Show which schemas match which discriminator values

## Related Documentation

- [OpenAPI 3.1 Discriminator Object](https://spec.openapis.org/oas/v3.1.0#discriminator-object)
- [JSON Schema Discriminator](https://json-schema.org/understanding-json-schema/reference/combining#discriminator)
- Class Composition documentation
- oneOf/anyOf/allOf usage guide

