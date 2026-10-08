# Discriminator Configuration - Visual Examples

## Example 1: Pet API with Custom Values

### Configuration
```
Class: Pet
Composition: oneOf
  - Dog
  - Cat
  - Bird

Discriminator Property: petType
Mapping Type: Explicit
```

### Mapping Configuration
```
┌──────────────────────────────────────────────────────────┐
│ Discriminator Configuration                              │
│                                                           │
│ Property Name: petType                                   │
│                                                           │
│ ☐ Use automatic mapping                                  │
│                                                           │
│ ┌────────────────────────────────────────────────────┐  │
│ │ Explicit Mapping                                   │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ canine   │    →    │    Dog       │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ feline   │    →    │    Cat       │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ avian    │    →    │    Bird      │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### Generated OpenAPI Schema
```yaml
Pet:
  type: object
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

### Example Request Body
```json
{
  "petType": "canine",
  "name": "Buddy",
  "breed": "Golden Retriever",
  "age": 5
}
```

---

## Example 2: Payment Methods with Automatic Mapping

### Configuration
```
Class: PaymentMethod
Composition: oneOf
  - CreditCard
  - BankTransfer
  - PayPal

Discriminator Property: type
Mapping Type: Automatic
```

### Mapping Configuration
```
┌──────────────────────────────────────────────────────────┐
│ Discriminator Configuration                              │
│                                                           │
│ Property Name: type                                      │
│                                                           │
│ ☑ Use automatic mapping                                  │
│   (implicit mapping based on schema names)               │
└──────────────────────────────────────────────────────────┘
```

### Generated OpenAPI Schema
```yaml
PaymentMethod:
  type: object
  oneOf:
    - $ref: '#/components/schemas/CreditCard'
    - $ref: '#/components/schemas/BankTransfer'
    - $ref: '#/components/schemas/PayPal'
  discriminator:
    propertyName: type
```

### Example Request Body
```json
{
  "type": "CreditCard",
  "cardNumber": "1234-5678-9012-3456",
  "expiryDate": "12/25",
  "cvv": "123"
}
```

---

## Example 3: Geometric Shapes with Multiple Values

### Configuration
```
Class: Shape
Composition: anyOf
  - Circle
  - Rectangle
  - Triangle

Discriminator Property: shapeType
Mapping Type: Explicit (with aliases)
```

### Mapping Configuration
```
┌──────────────────────────────────────────────────────────┐
│ Discriminator Configuration                              │
│                                                           │
│ Property Name: shapeType                                 │
│                                                           │
│ ☐ Use automatic mapping                                  │
│                                                           │
│ ┌────────────────────────────────────────────────────┐  │
│ │ Explicit Mapping                                   │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ circle   │    →    │   Circle     │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ rect     │    →    │  Rectangle   │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ tri      │    →    │  Triangle    │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### Generated OpenAPI Schema
```yaml
Shape:
  type: object
  anyOf:
    - $ref: '#/components/schemas/Circle'
    - $ref: '#/components/schemas/Rectangle'
    - $ref: '#/components/schemas/Triangle'
  discriminator:
    propertyName: shapeType
    mapping:
      circle: '#/components/schemas/Circle'
      rect: '#/components/schemas/Rectangle'
      tri: '#/components/schemas/Triangle'
```

---

## Example 4: Warning for Unmapped Schemas

### Configuration
```
Class: Animal
Composition: oneOf
  - Dog
  - Cat
  - Bird
  - Fish

Discriminator Property: animalType
Mapping Type: Explicit (incomplete)
```

### Mapping Configuration (with Warning)
```
┌──────────────────────────────────────────────────────────┐
│ Discriminator Configuration                              │
│                                                           │
│ Property Name: animalType                                │
│                                                           │
│ ☐ Use automatic mapping                                  │
│                                                           │
│ ┌────────────────────────────────────────────────────┐  │
│ │ Explicit Mapping                                   │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ dog      │    →    │    Dog       │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ cat      │    →    │    Cat       │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │          │    →    │    Bird      │  ← Empty!  │  │
│ │ └──────────┘         └──────────────┘            │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │          │    →    │    Fish      │  ← Empty!  │  │
│ │ └──────────┘         └──────────────┘            │  │
│ │                                                     │  │
│ │ ⚠ Warning: Unmapped schemas: Bird, Fish           │  │
│ │   These schemas won't be reachable via the        │  │
│ │   discriminator property.                         │  │
│ └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

**What happens:** Only Dog and Cat can be used. Bird and Fish are unreachable.

**Solution:** Either fill in mappings or remove Bird and Fish from oneOf.

---

## Example 5: Vehicle Hierarchy with Inheritance

### Configuration
```
Class: Vehicle (abstract)
Composition: 
  allOf: [BaseEntity]
  oneOf: [Car, Truck, Motorcycle, Bicycle]

Discriminator Property: vehicleType
Mapping Type: Explicit
```

### Mapping Configuration
```
┌──────────────────────────────────────────────────────────┐
│ Discriminator Configuration                              │
│                                                           │
│ Property Name: vehicleType                               │
│                                                           │
│ ☐ Use automatic mapping                                  │
│                                                           │
│ ┌────────────────────────────────────────────────────┐  │
│ │ Explicit Mapping                                   │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ car      │    →    │    Car       │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ truck    │    →    │   Truck      │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ moto     │    →    │ Motorcycle   │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌──────────────┐            │  │
│ │ │ bike     │    →    │  Bicycle     │            │  │
│ │ └──────────┘         └──────────────┘            │  │
│ └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### Generated OpenAPI Schema
```yaml
Vehicle:
  type: object
  allOf:
    - $ref: '#/components/schemas/BaseEntity'
  oneOf:
    - $ref: '#/components/schemas/Car'
    - $ref: '#/components/schemas/Truck'
    - $ref: '#/components/schemas/Motorcycle'
    - $ref: '#/components/schemas/Bicycle'
  discriminator:
    propertyName: vehicleType
    mapping:
      car: '#/components/schemas/Car'
      truck: '#/components/schemas/Truck'
      moto: '#/components/schemas/Motorcycle'
      bike: '#/components/schemas/Bicycle'
```

### Example Request Bodies

**Car:**
```json
{
  "vehicleType": "car",
  "make": "Toyota",
  "model": "Camry",
  "doors": 4,
  "hasAirConditioning": true
}
```

**Motorcycle:**
```json
{
  "vehicleType": "moto",
  "make": "Harley-Davidson",
  "model": "Street 750",
  "engineSize": 750,
  "hasSidecar": false
}
```

---

## Example 6: Error Response Types

### Configuration
```
Class: ErrorResponse
Composition: oneOf
  - ValidationError
  - AuthenticationError
  - NotFoundError
  - ServerError

Discriminator Property: errorType
Mapping Type: Explicit (error codes)
```

### Mapping Configuration
```
┌──────────────────────────────────────────────────────────┐
│ Discriminator Configuration                              │
│                                                           │
│ Property Name: errorType                                 │
│                                                           │
│ ☐ Use automatic mapping                                  │
│                                                           │
│ ┌────────────────────────────────────────────────────┐  │
│ │ Explicit Mapping                                   │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌────────────────────────┐  │  │
│ │ │ ERR_VAL  │    →    │  ValidationError       │  │  │
│ │ └──────────┘         └────────────────────────┘  │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌────────────────────────┐  │  │
│ │ │ ERR_AUTH │    →    │  AuthenticationError   │  │  │
│ │ └──────────┘         └────────────────────────┘  │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌────────────────────────┐  │  │
│ │ │ ERR_404  │    →    │  NotFoundError         │  │  │
│ │ └──────────┘         └────────────────────────┘  │  │
│ │                                                     │  │
│ │ ┌──────────┐    →    ┌────────────────────────┐  │  │
│ │ │ ERR_500  │    →    │  ServerError           │  │  │
│ │ └──────────┘         └────────────────────────┘  │  │
│ └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### Generated OpenAPI Schema
```yaml
ErrorResponse:
  type: object
  oneOf:
    - $ref: '#/components/schemas/ValidationError'
    - $ref: '#/components/schemas/AuthenticationError'
    - $ref: '#/components/schemas/NotFoundError'
    - $ref: '#/components/schemas/ServerError'
  discriminator:
    propertyName: errorType
    mapping:
      ERR_VAL: '#/components/schemas/ValidationError'
      ERR_AUTH: '#/components/schemas/AuthenticationError'
      ERR_404: '#/components/schemas/NotFoundError'
      ERR_500: '#/components/schemas/ServerError'
```

### Example Error Response
```json
{
  "errorType": "ERR_VAL",
  "message": "Validation failed",
  "fields": [
    {
      "field": "email",
      "error": "Invalid email format"
    }
  ]
}
```

---

## Workflow Comparison

### Before Enhancement

```
┌─────────────────────────────────────────┐
│ 1. Set discriminator property name     │
├─────────────────────────────────────────┤
│ 2. Check "Use automatic mapping"        │
├─────────────────────────────────────────┤
│ 3. Save                                 │
└─────────────────────────────────────────┘

Result: No control over property values
Values must match schema names exactly
```

### After Enhancement

```
┌─────────────────────────────────────────┐
│ 1. Set discriminator property name     │
├─────────────────────────────────────────┤
│ 2. Choose mapping type:                 │
│    ☑ Automatic (simple)                 │
│    OR                                   │
│    ☐ Explicit (custom)                  │
├─────────────────────────────────────────┤
│ 3. If explicit:                         │
│    - Fill in property values            │
│    - See visual mapping                 │
│    - Get validation warnings            │
├─────────────────────────────────────────┤
│ 4. Save                                 │
└─────────────────────────────────────────┘

Result: Full control over property values
Can use custom naming conventions
Visual feedback and validation
```

---

## Best Practices Illustrated

### ✅ Good: Consistent Lowercase Values

```
┌──────────┐    →    ┌──────────────┐
│ dog      │    →    │    Dog       │
└──────────┘         └──────────────┘

┌──────────┐    →    ┌──────────────┐
│ cat      │    →    │    Cat       │
└──────────┘         └──────────────┘

┌──────────┐    →    ┌──────────────┐
│ bird     │    →    │    Bird      │
└──────────┘         └──────────────┘
```

### ❌ Bad: Inconsistent Casing

```
┌──────────┐    →    ┌──────────────┐
│ Dog      │    →    │    Dog       │  ← Mixed case
└──────────┘         └──────────────┘

┌──────────┐    →    ┌──────────────┐
│ cat      │    →    │    Cat       │  ← Different from above
└──────────┘         └──────────────┘

┌──────────┐    →    ┌──────────────┐
│ BIRD     │    →    │    Bird      │  ← All uppercase
└──────────┘         └──────────────┘
```

### ✅ Good: Descriptive Values

```
┌──────────┐    →    ┌──────────────┐
│ credit   │    →    │  CreditCard  │
└──────────┘         └──────────────┘

┌──────────┐    →    ┌──────────────┐
│ bank     │    →    │ BankTransfer │
└──────────┘         └──────────────┘

┌──────────┐    →    ┌──────────────┐
│ paypal   │    →    │   PayPal     │
└──────────┘         └──────────────┘
```

### ❌ Bad: Unclear Abbreviations

```
┌──────────┐    →    ┌──────────────┐
│ cc       │    →    │  CreditCard  │  ← What does cc mean?
└──────────┘         └──────────────┘

┌──────────┐    →    ┌──────────────┐
│ bt       │    →    │ BankTransfer │  ← Not obvious
└──────────┘         └──────────────┘

┌──────────┐    →    ┌──────────────┐
│ pp       │    →    │   PayPal     │  ← Too short
└──────────┘         └──────────────┘
```

---

## Summary

The enhanced discriminator configuration provides:
- **Visual clarity** through arrow notation and highlighted schema names
- **Real-time validation** with warnings for unmapped schemas
- **Flexibility** to use custom property values
- **Consistency** enforcement through visual feedback
- **Ease of use** with intuitive input fields
- **Power** to handle complex polymorphic scenarios

Choose automatic mapping for simple cases, explicit mapping when you need control over property values.

