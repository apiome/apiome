# Quick Reference: Exclusive/Inclusive Min/Max

## UI Elements

```
┌─────────────────────────────────────────────┐
│ Minimum: [10        ]                       │
│ ⦿ Inclusive (≥)  ◯ Exclusive (>)           │
└─────────────────────────────────────────────┘
```

## Output Mapping

| Radio Selection | JSON Field | Meaning |
|----------------|------------|---------|
| Inclusive (≥) | `minimum` | value ≥ X |
| Exclusive (>) | `exclusiveMinimum` | value > X |
| Inclusive (≤) | `maximum` | value ≤ X |
| Exclusive (<) | `exclusiveMaximum` | value < X |

## Quick Examples

### Positive Numbers (value > 0)
```
Input:  minimum = 0, Exclusive (>)
Output: "exclusiveMinimum": 0
```

### Percentage (0 ≤ value ≤ 100)
```
Input:  minimum = 0, Inclusive (≥)
        maximum = 100, Inclusive (≤)
Output: "minimum": 0, "maximum": 100
```

### Probability (0 < value < 1)
```
Input:  minimum = 0, Exclusive (>)
        maximum = 1, Exclusive (<)
Output: "exclusiveMinimum": 0, "exclusiveMaximum": 1
```

### Age (0 < age ≤ 150)
```
Input:  minimum = 0, Exclusive (>)
        maximum = 150, Inclusive (≤)
Output: "exclusiveMinimum": 0, "maximum": 150
```

## Rules

✅ **Only one field output** - Either `minimum` OR `exclusiveMinimum` (never both)
✅ **Same value, different field** - The number stays the same, only field name changes
✅ **Auto-default** - First value entry defaults to Inclusive
✅ **Auto-clear** - Clearing value also clears type selection
✅ **NaN protected** - Invalid input won't generate schema fields
✅ **Zero supported** - Zero is a valid value (not treated as empty)

## Common Patterns

| Use Case | Configuration | JSON Output |
|----------|---------------|-------------|
| Positive integer | min=0, Exclusive | `"exclusiveMinimum": 0` |
| Non-negative | min=0, Inclusive | `"minimum": 0` |
| Rating 1-5 | min=1 (Inc), max=5 (Inc) | `"minimum": 1, "maximum": 5` |
| Percentage | min=0 (Inc), max=100 (Inc) | `"minimum": 0, "maximum": 100` |
| Probability | min=0 (Ex), max=1 (Ex) | `"exclusiveMinimum": 0, "exclusiveMaximum": 1` |
| Temperature > -273.15°C | min=-273.15, Exclusive | `"exclusiveMinimum": -273.15` |

## Validation

```typescript
// Checked before adding to schema:
1. formData.minimum exists ✓
2. formData.minimum.trim() is not empty ✓
3. parseFloat(formData.minimum) is valid number ✓
4. Result is not NaN ✓
```

## Fixes Applied

1. ✅ Type cleared when value removed
2. ✅ NaN validation prevents invalid output
3. ✅ Trim whitespace before validation
4. ✅ Explicit number parsing and validation
5. ✅ Array types load constraints from items object

## Standards

- OpenAPI 3.1.x ✓
- JSON Schema draft 2020-12 ✓
- JSON Schema draft 2019-09 ✓

---

**TIP:** Use "Exclusive" when you want strictly greater/less than (>/<)
**TIP:** Use "Inclusive" when you want greater/less than or equal (≥/≤)

