# Exclusive Minimum/Maximum Examples

This document provides practical examples of using the exclusive minimum/maximum feature in the property form, demonstrating the OpenAPI 3.1 / JSON Schema draft 2020-12 compliance.

## Basic Examples

### Example 1: Positive Integer (value > 0)

**Property Configuration:**
- Type: `integer`
- Minimum: `0`
- Minimum Type: `Exclusive (>)`

**Generated Schema:**
```json
{
  "type": "integer",
  "exclusiveMinimum": 0
}
```

**Valid values:** 1, 2, 3, 4, ...
**Invalid values:** 0, -1, -2, ...

---

### Example 2: Percentage (0 ≤ value ≤ 100)

**Property Configuration:**
- Type: `number`
- Minimum: `0`
- Minimum Type: `Inclusive (≥)`
- Maximum: `100`
- Maximum Type: `Inclusive (≤)`

**Generated Schema:**
```json
{
  "type": "number",
  "minimum": 0,
  "maximum": 100
}
```

**Valid values:** 0, 0.5, 50, 99.9, 100
**Invalid values:** -0.1, 100.1

---

### Example 3: Probability (0 < value < 1)

**Property Configuration:**
- Type: `number`
- Minimum: `0`
- Minimum Type: `Exclusive (>)`
- Maximum: `1`
- Maximum Type: `Exclusive (<)`

**Generated Schema:**
```json
{
  "type": "number",
  "exclusiveMinimum": 0,
  "exclusiveMaximum": 1
}
```

**Valid values:** 0.001, 0.5, 0.999
**Invalid values:** 0, 1, -0.5, 1.5

---

### Example 4: Temperature in Celsius (above absolute zero)

**Property Configuration:**
- Type: `number`
- Minimum: `-273.15`
- Minimum Type: `Exclusive (>)`

**Generated Schema:**
```json
{
  "type": "number",
  "exclusiveMinimum": -273.15
}
```

**Valid values:** -273.14, -100, 0, 25, 100
**Invalid values:** -273.15, -300

---

### Example 5: Rating (1 to 5 stars)

**Property Configuration:**
- Type: `integer`
- Minimum: `1`
- Minimum Type: `Inclusive (≥)`
- Maximum: `5`
- Maximum Type: `Inclusive (≤)`

**Generated Schema:**
```json
{
  "type": "integer",
  "minimum": 1,
  "maximum": 5
}
```

**Valid values:** 1, 2, 3, 4, 5
**Invalid values:** 0, 6

---

## Array Examples

### Example 6: Array of Positive Numbers

**Property Configuration:**
- Type: `number`
- Is Array: ✓
- Minimum: `0`
- Minimum Type: `Exclusive (>)`

**Generated Schema:**
```json
{
  "type": "array",
  "items": {
    "type": "number",
    "exclusiveMinimum": 0
  }
}
```

**Valid values:** `[1, 2.5, 100]`
**Invalid values:** `[0, 5, 10]`, `[-1, 5, 10]`

---

## Real-World Use Cases

### Age Validation (0 < age ≤ 150)

```json
{
  "type": "integer",
  "exclusiveMinimum": 0,
  "maximum": 150,
  "description": "Person's age in years"
}
```

### Price (must be positive)

```json
{
  "type": "number",
  "exclusiveMinimum": 0,
  "description": "Price in USD",
  "example": 19.99
}
```

### Discount Percentage (0 ≤ discount < 100)

```json
{
  "type": "number",
  "minimum": 0,
  "exclusiveMaximum": 100,
  "description": "Discount percentage"
}
```

### Latitude (-90 ≤ lat ≤ 90)

```json
{
  "type": "number",
  "minimum": -90,
  "maximum": 90,
  "description": "Latitude coordinate"
}
```

### Longitude (-180 ≤ lon < 180)

```json
{
  "type": "number",
  "minimum": -180,
  "exclusiveMaximum": 180,
  "description": "Longitude coordinate"
}
```

---

## Migration from OpenAPI 3.0

### Before (OpenAPI 3.0 style)

```json
{
  "type": "number",
  "minimum": 0,
  "exclusiveMinimum": true
}
```

### After (OpenAPI 3.1 style)

```json
{
  "type": "number",
  "exclusiveMinimum": 0
}
```

The new format is:
- ✅ More intuitive
- ✅ Compliant with JSON Schema draft 2020-12
- ✅ Required for OpenAPI 3.1.x

---

## UI Workflow

1. **Create/Edit Property:** Open the property dialog
2. **Set Type:** Choose `number` or `integer`
3. **Enter Minimum:** Type the minimum value
4. **Select Type:** Choose either:
   - `Inclusive (≥)` - value can equal minimum
   - `Exclusive (>)` - value must be greater than minimum
5. **Enter Maximum:** (optional) Type the maximum value
6. **Select Type:** Choose either:
   - `Inclusive (≤)` - value can equal maximum
   - `Exclusive (<)` - value must be less than maximum
7. **Save:** The correct schema field is automatically generated

---

## Validation Notes

- Radio buttons are disabled until a value is entered
- Default selection is "Inclusive" when a value is first entered
- Only one of `minimum` or `exclusiveMinimum` will be in the output
- Only one of `maximum` or `exclusiveMaximum` will be in the output
- The UI prevents invalid combinations

---

## Testing the Implementation

### Test Case 1: Create Exclusive Minimum
1. Add a number property
2. Set minimum to `0`
3. Select "Exclusive (>)"
4. Switch to JSON view
5. Verify: `"exclusiveMinimum": 0` appears (not `"minimum": 0`)

### Test Case 2: Create Mixed Constraints
1. Add a number property
2. Set minimum to `0`, select "Exclusive (>)"
3. Set maximum to `100`, select "Inclusive (≤)"
4. Switch to JSON view
5. Verify both: `"exclusiveMinimum": 0` and `"maximum": 100`

### Test Case 3: Edit Existing Property
1. Edit a property that has `"minimum": 5`
2. Verify "Inclusive (≥)" is selected
3. Change to "Exclusive (>)"
4. Save and reopen
5. Verify schema changed to `"exclusiveMinimum": 5`

---

## Standards References

- [JSON Schema Validation - Numeric Constraints](https://json-schema.org/draft/2020-12/json-schema-validation.html#name-validation-keywords-for-num)
- [OpenAPI 3.1.0 - Schema Object](https://spec.openapis.org/oas/v3.1.0#schema-object)
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12/json-schema-core.html)

