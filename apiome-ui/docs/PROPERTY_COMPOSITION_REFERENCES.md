# Property Composition References Feature

## Overview

Properties in the Apiome schema designer can now reference multiple classes using JSON Schema composition keywords: `allOf`, `anyOf`, and `oneOf`. This feature enables complex type relationships similar to how ClassNode implements composition, but at the property level.

## Feature Description

### Single Reference (Existing)
Previously, properties could only reference a single class:
- Direct `$ref`: Points to one class
- Array with `$ref` in items: Array of references to one class

### Multiple References (New)
Properties can now use composition types to reference multiple classes:
- **allOf**: Property must satisfy ALL referenced schemas (intersection/inheritance)
- **anyOf**: Property can satisfy ANY of the referenced schemas (union)
- **oneOf**: Property must satisfy EXACTLY ONE referenced schema (exclusive choice)

### Composition in Arrays
Composition can be applied at the property level or within array items:
- `allOf` at property level: Direct composition
- `allOf` in array items: Array of composed types

## User Interface

### Reference Dialog Enhancements

When creating a reference property, users now see:

1. **Reference Type Selection**
   - Radio buttons to choose between:
     - Single Reference (default)
     - allOf (Composition/Inheritance)
     - anyOf (Union)
     - oneOf (Exclusive)

2. **Single Reference Mode**
   - Dropdown to select target class (optional)
   - Can be connected later via canvas

3. **Composition Mode** (allOf/anyOf/oneOf)
   - Dropdown to add multiple classes
   - Selected classes displayed as chips
   - Can remove classes by clicking X on chip
   - At least one class required for composition types

4. **Array Options** (Existing)
   - Checkbox for "Array of references"
   - Min/Max items constraints
   - Unique items option

### Visual Representation

#### Property Type Display
Properties with composition show formatted type information:
- `allOf(User, Admin)` - Must satisfy both User and Admin
- `anyOf(Email | Phone)[]` - Array of either Email or Phone
- `oneOf(Credit | Debit | Cash)` - Exactly one payment method

#### Canvas Edges
Composition properties create multiple edges with distinct styling:

**allOf (Inheritance)**
- Color: Blue (#2563eb)
- Style: Solid line
- Label: "propertyName (allOf)"

**anyOf (Union)**
- Color: Orange (#ea580c)
- Style: Dashed line (5,5)
- Label: "propertyName (anyOf)"

**oneOf (Exclusive)**
- Color: Purple (#9333ea)
- Style: Dotted line (2,3)
- Label: "propertyName (oneOf)"

## Implementation Details

### Data Structure

#### Single Reference
```json
{
  "name": "owner",
  "data": {
    "$ref": "#/components/schemas/User"
  }
}
```

#### allOf Example
```json
{
  "name": "admin",
  "data": {
    "allOf": [
      { "$ref": "#/components/schemas/User" },
      { "$ref": "#/components/schemas/Administrator" }
    ]
  }
}
```

#### anyOf in Array Example
```json
{
  "name": "contacts",
  "data": {
    "type": "array",
    "items": {
      "anyOf": [
        { "$ref": "#/components/schemas/Email" },
        { "$ref": "#/components/schemas/Phone" }
      ]
    }
  }
}
```

### Modified Components

#### 1. ReferenceDialog.tsx
**Changes:**
- Added composition type state and UI
- Added multiple class selection
- Updated form validation
- Enhanced submission to pass composition data

**New Props:**
```typescript
interface ReferenceDialogProps {
  // ... existing props
  onSubmit: (referenceData: {
    name: string;
    description: string | null;
    isArray: boolean;
    targetClassId: string | null;
    targetClassIds?: string[];        // NEW
    compositionType?: CompositionType; // NEW
    minItems?: number;
    maxItems?: number;
    uniqueItems?: boolean;
  }) => Promise<void>;
}

type CompositionType = 'none' | 'allOf' | 'anyOf' | 'oneOf';
```

#### 2. ClassNode.tsx
**Changes:**
- Enhanced `getPropertyType()` to display composition types
- Enhanced `hasRef()` to recognize composition properties
- Added composition display for array items

**Type Display Logic:**
```typescript
// Direct composition
if (d?.allOf) return `allOf(${types.join(', ')})`;
if (d?.anyOf) return `anyOf(${types.join(' | ')})`;
if (d?.oneOf) return `oneOf(${types.join(' | ')})`;

// Array items composition
if (d.items?.allOf) return `allOf(${types.join(', ')})[]`;
// ... etc
```

#### 3. studio/page.tsx
**Changes:**
- Updated `handleReferenceSubmit()` to build composition data
- Enhanced `createPropertyRefEdges()` to create composition edges
- Added composition edge styling logic

**Edge Creation:**
```typescript
// Creates multiple edges for composition properties
// Each reference in allOf/anyOf/oneOf gets its own edge
// Edges styled differently based on composition type
```

## Usage Examples

### Example 1: User Admin (allOf)
Create a property that must satisfy both User and Admin schemas:

1. Click "Create Reference" on a class
2. Enter name: "userAdmin"
3. Select "allOf (Composition/Inheritance)"
4. Add "User" class
5. Add "Admin" class
6. Submit

Result: Property with type `allOf(User, Admin)`

### Example 2: Payment Methods (oneOf)
Create a property that accepts exactly one payment method:

1. Create reference named "paymentMethod"
2. Select "oneOf (Exclusive)"
3. Add "CreditCard", "DebitCard", "Cash"
4. Submit

Result: Property with type `oneOf(CreditCard | DebitCard | Cash)`

### Example 3: Contact Array (anyOf)
Create an array that can contain emails or phones:

1. Create reference named "contacts"
2. Check "Array of references"
3. Select "anyOf (Union)"
4. Add "Email" and "Phone"
5. Submit

Result: Property with type `anyOf(Email | Phone)[]`

## OpenAPI Schema Generation

The composition references generate standard JSON Schema constructs:

```json
{
  "properties": {
    "admin": {
      "allOf": [
        { "$ref": "#/components/schemas/User" },
        { "$ref": "#/components/schemas/Administrator" }
      ]
    },
    "contactInfo": {
      "anyOf": [
        { "$ref": "#/components/schemas/Email" },
        { "$ref": "#/components/schemas/Phone" }
      ]
    },
    "paymentMethod": {
      "oneOf": [
        { "$ref": "#/components/schemas/CreditCard" },
        { "$ref": "#/components/schemas/Cash" }
      ]
    },
    "contacts": {
      "type": "array",
      "items": {
        "anyOf": [
          { "$ref": "#/components/schemas/Email" },
          { "$ref": "#/components/schemas/Phone" }
        ]
      }
    }
  }
}
```

## Technical Notes

### Composition Semantics

**allOf** - Intersection/Inheritance
- Instance must be valid against ALL schemas
- Properties are merged
- Use for: Inheritance, mixins, composition

**anyOf** - Union
- Instance must be valid against AT LEAST ONE schema
- Use for: Alternative representations, polymorphism

**oneOf** - Exclusive Choice
- Instance must be valid against EXACTLY ONE schema
- Use for: Discriminated unions, exclusive alternatives

### Edge Z-Index
Composition edges use `zIndex: 10 + index` to properly layer multiple edges from the same property.

### Canvas Connections
Currently, composition properties are created with all references selected upfront. Future enhancement could allow:
- Connecting additional references via canvas
- Removing references via canvas
- Converting single reference to composition

## Benefits

1. **Expressive Type System**: Model complex relationships accurately
2. **Visual Clarity**: Different edge styles make relationships obvious
3. **Standards Compliant**: Uses standard JSON Schema keywords
4. **Flexible**: Works with single items or arrays
5. **Consistent**: Mirrors class-level composition implementation

## Future Enhancements

1. **Canvas Editing**: Add/remove composition references via drag-and-drop
2. **Type Inference**: Suggest composition types based on usage
3. **Validation**: Real-time validation of composition semantics
4. **Import/Export**: Support importing schemas with composition
5. **Documentation**: Auto-generate documentation for composed properties

## Testing Checklist

- [ ] Create property with allOf
- [ ] Create property with anyOf
- [ ] Create property with oneOf
- [ ] Create array with allOf in items
- [ ] Create array with anyOf in items
- [ ] Create array with oneOf in items
- [ ] Verify edges display correctly
- [ ] Verify property type labels are correct
- [ ] Edit property with composition
- [ ] Delete property with composition
- [ ] Export OpenAPI spec with composition
- [ ] Verify generated JSON is valid
- [ ] Test with 2+ classes in composition
- [ ] Test read-only mode

## Related Features

- Class Composition: Classes can use allOf/anyOf/oneOf for inheritance
- Property References: Properties can reference single classes
- Nested Properties: Properties can contain nested object structures
- Array Properties: Properties can be arrays with constraints

## See Also

- [Class Composition Documentation](./CLASS_COMPOSITION_FEATURE.md) _(if exists)_
- [Property References Guide](./PROPERTY_REFERENCES.md) _(if exists)_
- [JSON Schema Composition Keywords](https://json-schema.org/understanding-json-schema/reference/combining.html)

