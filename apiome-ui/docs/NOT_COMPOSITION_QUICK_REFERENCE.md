# NOT Composition Quick Reference

## What is NOT Composition?

NOT composition allows you to specify a schema that your data must **NOT** match. It's useful for exclusion rules like "not an empty string" or "not a specific value".

## How to Use

### Quick Steps

1. **Open Property Editor**
   - Create new or edit existing property

2. **Scroll to NOT Composition Section**
   - Located at the bottom of the right column
   - After Object Constraints

3. **Enter NOT Schema**
   - Write JSON schema in the text field
   - Use examples as templates

4. **Save Property**
   - NOT validation will be applied

## Common Examples

### Exclude Empty Strings
```json
{"type": "string", "maxLength": 0}
```
**Result:** Allows any non-empty string

### Exclude Null
```json
{"type": "null"}
```
**Result:** Allows any value except null

### Exclude Specific Value
```json
{"const": "forbidden"}
```
**Result:** Allows any value except "forbidden"

### Exclude Negative Numbers
```json
{"maximum": 0}
```
**Result:** Allows only positive numbers

### Exclude Empty Arrays
```json
{"maxItems": 0}
```
**Result:** Array must have at least one item

### Exclude Pattern
```json
{"pattern": "^test-"}
```
**Result:** String cannot start with "test-"

## Syntax

### Basic Format
```json
{
  "not": {
    // Schema to exclude
  }
}
```

### For String Properties
```json
{
  "type": "string",
  "not": {
    "maxLength": 0
  }
}
```

### For Number Properties
```json
{
  "type": "number",
  "not": {
    "maximum": 0
  }
}
```

### For Array Properties
```json
{
  "type": "array",
  "items": {
    "type": "string",
    "not": {
      "maxLength": 0
    }
  }
}
```

## Real-World Examples

### Username Field
```json
{"not": {"pattern": "^(admin|root|system)$"}}
```
**Purpose:** Username cannot be admin, root, or system

### Product Price
```json
{"not": {"maximum": 0}}
```
**Purpose:** Price must be positive

### Email List
```json
{
  "type": "array",
  "items": {
    "type": "string",
    "not": {"maxLength": 0}
  }
}
```
**Purpose:** Array of non-empty email addresses

### Status Field
```json
{"not": {"const": "DELETED"}}
```
**Purpose:** Status can be anything except DELETED

### Age Field
```json
{"not": {"maximum": 0}}
```
**Purpose:** Age must be positive

## How It Works

### Validation Logic

The NOT keyword **inverts** the validation:
- If data **matches** the NOT schema → ❌ **Invalid**
- If data **doesn't match** the NOT schema → ✅ **Valid**

### Example
```json
{
  "type": "string",
  "not": {
    "maxLength": 0
  }
}
```

**Valid Values:**
- `"hello"` ✅ (string with length > 0)
- `"a"` ✅ (string with length > 0)

**Invalid Values:**
- `""` ❌ (string with length 0, matches NOT schema)

## Tips

### Best Practices
- ✅ Use for exclusion rules
- ✅ Keep NOT schemas simple
- ✅ Combine with positive validation
- ✅ Test validation logic
- ✅ Document why values are excluded

### Common Mistakes
- ❌ Using NOT for simple validation
- ❌ Creating complex NOT schemas
- ❌ Double negatives (confusing)
- ❌ Not testing edge cases

### When to Use NOT
- ✅ Excluding specific values
- ✅ Excluding patterns
- ✅ Excluding ranges
- ✅ Excluding specific structures

### When NOT to Use NOT
- ❌ Simple type validation (use `type`)
- ❌ Value lists (use `enum`)
- ❌ Range validation (use `minimum`/`maximum`)
- ❌ Simple patterns (use `pattern`)

## Troubleshooting

### NOT Schema Not Working

**Check:**
1. Is JSON valid?
2. Is NOT schema itself valid?
3. Are there conflicting rules?

### JSON Parse Error

**Solutions:**
1. Validate JSON syntax
2. Check quotes (must be double quotes)
3. Remove trailing commas
4. Use JSON validator tool

### Unexpected Results

**Remember:**
- NOT **inverts** validation
- Data must **NOT** match the schema
- Test with sample values

## Examples by Type

### String Examples

**Non-empty:**
```json
{"maxLength": 0}
```

**Not whitespace only:**
```json
{"pattern": "^\\s+$"}
```

**Not starting with prefix:**
```json
{"pattern": "^test-"}
```

### Number Examples

**Positive only:**
```json
{"maximum": 0}
```

**Not zero:**
```json
{"const": 0}
```

**Outside range:**
```json
{"minimum": 10, "maximum": 20}
```

### Object Examples

**No deprecated field:**
```json
{"required": ["deprecatedField"]}
```

**No extra properties:**
```json
{"additionalProperties": true}
```

### Array Examples

**Not empty:**
```json
{"maxItems": 0}
```

**Items not empty strings:**
```json
{
  "items": {
    "type": "string",
    "maxLength": 0
  }
}
```

## Combining with Other Validations

### Required Non-Empty String
```json
{
  "type": "string",
  "minLength": 1,
  "not": {
    "pattern": "^\\s+$"
  }
}
```

### Positive Integer
```json
{
  "type": "integer",
  "minimum": 1,
  "not": {
    "maximum": 0
  }
}
```
(Note: `minimum: 1` is simpler!)

### Non-Null String
```json
{
  "type": "string",
  "not": {
    "type": "null"
  }
}
```

## For Arrays vs Non-Arrays

### For Array Properties
- NOT schema applies to **each item**
- Entered in items constraint section
- Helper text says: "NOT schema applies to each item in the array"

### For Non-Array Properties
- NOT schema applies to **the property value**
- Entered in composition section
- Helper text shows example for property type

## Testing Your NOT Schema

### Step 1: Write NOT Schema
```json
{"maxLength": 0}
```

### Step 2: Think About What Should Be Invalid
- Empty string `""` should be invalid

### Step 3: Think About What Should Be Valid
- Any non-empty string should be valid

### Step 4: Test
- Try saving with empty value → should fail
- Try saving with non-empty value → should pass

## Quick Reference Card

| Goal | NOT Schema |
|------|------------|
| Not empty string | `{"maxLength": 0}` |
| Not null | `{"type": "null"}` |
| Not specific value | `{"const": "value"}` |
| Not negative | `{"maximum": 0}` |
| Not in list | `{"enum": ["a", "b"]}` |
| Not pattern | `{"pattern": "regex"}` |
| Not empty array | `{"maxItems": 0}` |
| Not empty object | `{"maxProperties": 0}` |

## Need Help?

- See full documentation: `/docs/NOT_COMPOSITION_FEATURE.md`
- JSON Schema docs: https://json-schema.org
- Test your schema: https://www.jsonschemavalidator.net
- Ask your team lead

---

**Quick Tip:** NOT inverts validation. If your data matches the NOT schema, it's **invalid**!

