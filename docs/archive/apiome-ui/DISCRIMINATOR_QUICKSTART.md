# Discriminator Configuration - Quick Reference

## What is a Discriminator?

A discriminator is a property that tells code generators and validators which specific schema to use when multiple options are available (oneOf, anyOf, allOf). Think of it as a "type indicator" property.

## When to Use Discriminators

Use discriminators when you have:
- **Polymorphic types**: Multiple schemas that can be used in the same place
- **oneOf compositions**: Where exactly one schema must match
- **anyOf/allOf compositions**: Where type indication helps with deserialization

### Example Scenario
You have a Pet API with Dog, Cat, and Bird types. Each request could be any of these types. The discriminator property (e.g., "petType") tells the system which specific type it is.

## How to Configure

### Step 1: Set Up Composition
Add schemas to oneOf, anyOf, or allOf in your class definition.

Example:
- oneOf: [Dog, Cat, Bird]

### Step 2: Open Discriminator Configuration
The "Discriminator Configuration" section appears automatically when you have composition schemas.

### Step 3: Set Property Name
Enter the property name that will indicate the type.

**Good Examples:**
- `type`
- `petType`
- `kind`
- `vehicleKind`
- `shapeType`

**What it means:**
This property must exist in all schemas and its value determines which schema is being used.

### Step 4: Choose Mapping Type

#### Option A: Automatic Mapping (Recommended for Simple Cases)
- ✅ Check "Use automatic mapping"
- No additional configuration needed
- Property values implicitly match schema names
- Cleaner OpenAPI output

**When to use:**
- Property values match schema names exactly
- Simple type indicators
- Standard naming conventions

**Example:**
```json
{
  "type": "Dog"  // Maps to Dog schema
}
```

#### Option B: Explicit Mapping (Custom Values)
- ☐ Uncheck "Use automatic mapping"
- Configure custom property value → schema mappings
- More control over property values

**When to use:**
- Property values differ from schema names
- Need lowercase/uppercase variations
- Multiple values map to same schema
- Business-specific naming

**Example:**
```json
{
  "petType": "dog"  // Maps to Dog schema (lowercase)
}
```

## Configuring Explicit Mapping

### The Mapping Editor

When explicit mapping is enabled, you'll see:

```
Property Value  →  Schema Name
┌─────────────┐    ┌──────────┐
│ dog         │ → │   Dog    │
└─────────────┘    └──────────┘

┌─────────────┐    ┌──────────┐
│ cat         │ → │   Cat    │
└─────────────┘    └──────────┘
```

- **Left side**: Enter the value that will appear in the discriminator property
- **Right side**: The schema it maps to (read-only)

### Filling in Values

For each schema:
1. Click in the left input field
2. Type the property value
3. Value automatically maps to the schema

**Tips:**
- Use lowercase for consistency: `dog`, `cat`, `bird`
- Use descriptive names: `canine`, `feline`, `avian`
- Match your API's naming convention
- Be consistent across all mappings

### Validation Warnings

If you leave any schemas unmapped, you'll see:

```
⚠ Warning: Unmapped schemas: Bird
  These schemas won't be reachable via the discriminator property.
```

**What it means:**
- The Bird schema has no property value mapping
- Clients won't be able to use Bird type
- Either add a mapping or remove the schema from composition

## Examples

### Example 1: Pet API (oneOf with Explicit Mapping)

**Setup:**
- oneOf: [Dog, Cat, Bird]
- Discriminator Property: `petType`
- Mapping Type: Explicit

**Mappings:**
| Property Value | Schema |
|----------------|--------|
| canine         | Dog    |
| feline         | Cat    |
| avian          | Bird   |

**Generated Schema:**
```yaml
oneOf:
  - $ref: '#/components/schemas/Dog'
  - $ref: '#/components/schemas/Cat'
  - $ref: '#/components/schemas/Bird'
discriminator:
  propertyName: petType
  mapping:
    canine: '#/components/schemas/Dog'
    feline: '#/components/schemas/Cat'
    avian: '#/components/schemas/Bird'
```

**Example Request:**
```json
{
  "petType": "canine",
  "name": "Buddy",
  "breed": "Golden Retriever"
}
```

### Example 2: Payment Method (oneOf with Auto Mapping)

**Setup:**
- oneOf: [CreditCard, BankTransfer, PayPal]
- Discriminator Property: `type`
- Mapping Type: Automatic

**Generated Schema:**
```yaml
oneOf:
  - $ref: '#/components/schemas/CreditCard'
  - $ref: '#/components/schemas/BankTransfer'
  - $ref: '#/components/schemas/PayPal'
discriminator:
  propertyName: type
```

**Example Request:**
```json
{
  "type": "CreditCard",
  "cardNumber": "1234-5678-9012-3456",
  "expiryDate": "12/25"
}
```

### Example 3: Geometric Shapes (anyOf)

**Setup:**
- anyOf: [Circle, Rectangle, Triangle]
- Discriminator Property: `shape`
- Mapping Type: Explicit

**Mappings:**
| Property Value | Schema    |
|----------------|-----------|
| circle         | Circle    |
| rectangle      | Rectangle |
| triangle       | Triangle  |

**Generated Schema:**
```yaml
anyOf:
  - $ref: '#/components/schemas/Circle'
  - $ref: '#/components/schemas/Rectangle'
  - $ref: '#/components/schemas/Triangle'
discriminator:
  propertyName: shape
  mapping:
    circle: '#/components/schemas/Circle'
    rectangle: '#/components/schemas/Rectangle'
    triangle: '#/components/schemas/Triangle'
```

### Example 4: Vehicle Types (Inheritance with oneOf)

**Setup:**
- allOf: [Vehicle]
- oneOf: [Car, Truck, Motorcycle]
- Discriminator Property: `vehicleType`
- Mapping Type: Explicit

**Mappings:**
| Property Value | Schema     |
|----------------|------------|
| car            | Car        |
| truck          | Truck      |
| motorcycle     | Motorcycle |

**Generated Schema:**
```yaml
allOf:
  - $ref: '#/components/schemas/Vehicle'
oneOf:
  - $ref: '#/components/schemas/Car'
  - $ref: '#/components/schemas/Truck'
  - $ref: '#/components/schemas/Motorcycle'
discriminator:
  propertyName: vehicleType
  mapping:
    car: '#/components/schemas/Car'
    truck: '#/components/schemas/Truck'
    motorcycle: '#/components/schemas/Motorcycle'
```

## Best Practices

### 1. Choose Meaningful Property Names
✅ **Good:**
- `type`, `kind`, `category`
- `petType`, `vehicleType`, `shapeType`
- Domain-specific: `paymentMethod`, `userRole`

❌ **Avoid:**
- Generic: `t`, `k`, `discriminator`
- Confusing: `value`, `name`, `id`

### 2. Be Consistent with Values
✅ **Good:**
- All lowercase: `dog`, `cat`, `bird`
- All uppercase: `DOG`, `CAT`, `BIRD`
- Kebab-case: `credit-card`, `bank-transfer`

❌ **Avoid:**
- Mixed case: `Dog`, `cat`, `BIRD`
- Inconsistent format: `credit_card`, `BankTransfer`, `pay-pal`

### 3. Use Explicit Mapping When Needed
Use explicit mapping if:
- Property values should be lowercase
- Values don't match schema names
- Using abbreviations or codes
- Supporting legacy value names

Use automatic mapping if:
- Property values match schema names exactly
- Simple, straightforward mapping
- Following standard conventions

### 4. Document the Discriminator
In your schema descriptions, mention:
- Which property is the discriminator
- What values are valid
- Which schema each value maps to

Example:
```
Description: "Represents a pet. Use 'petType' property to specify the type:
- 'canine' for dogs
- 'feline' for cats  
- 'avian' for birds"
```

### 5. Ensure Property Exists in All Schemas
Every schema in the composition should have the discriminator property:

```yaml
Dog:
  type: object
  properties:
    petType:
      type: string
      const: canine  # Or enum with single value
    name:
      type: string
    breed:
      type: string
  required:
    - petType  # Make it required!
```

## Troubleshooting

### "Discriminator Configuration section not showing"
**Cause:** No schemas in oneOf, anyOf, or allOf
**Solution:** Add at least one schema to a composition type

### "Warning: Unmapped schemas"
**Cause:** Some schemas don't have property value mappings
**Solution:** Either:
- Add mappings for all schemas
- Remove unused schemas from composition
- Switch to automatic mapping

### "Code generator not using discriminator"
**Cause:** Discriminator property might not exist in all schemas
**Solution:** 
- Add discriminator property to each schema
- Make it required in the schema
- Consider using `const` or single-value `enum` for the discriminator value

### "Which mapping type should I use?"
**Automatic:** Property values = schema names (e.g., "Dog" → Dog)
**Explicit:** Custom property values (e.g., "dog" → Dog, "canine" → Dog)

**Rule of thumb:** Start with automatic. Switch to explicit if you need custom values.

## Quick Checklist

Before saving a class with discriminator:

- [ ] Discriminator property name is clear and meaningful
- [ ] Property name doesn't conflict with other properties
- [ ] Chosen appropriate mapping type (auto vs explicit)
- [ ] If explicit: all schemas have mappings (or intentionally unmapped)
- [ ] Values are consistent in format
- [ ] Discriminator property exists in all referenced schemas
- [ ] Discriminator property is marked as required in schemas

## Related Topics

- Class Composition (oneOf, anyOf, allOf)
- Polymorphic Types in OpenAPI
- Schema Inheritance
- Code Generation Best Practices

## Need Help?

See the detailed [Discriminator Feature Documentation](./DISCRIMINATOR_FEATURE.md) for technical details and advanced use cases.

