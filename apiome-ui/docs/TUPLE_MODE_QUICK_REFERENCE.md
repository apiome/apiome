# Tuple Mode Quick Reference

## Enable Tuple Mode

1. Open property dialog
2. Set type to "Array"
3. Check "Tuple Mode (prefixItems)" checkbox

## Add Positions

- Click "Add Position"
- Select type from dropdown
- Edit JSON schema in text area
- Drag ⋮ to reorder
- Click 🗑️ to delete

## Items Schema

Controls items beyond prefix positions:

| Value | Behavior |
|-------|----------|
| `true` (default) | Allow any additional items |
| `false` | Strict tuple, no additional items |
| `{"type": "string"}` | Additional items must be strings |
| Any JSON Schema | Additional items must match schema |

## Example: Coordinate Tuple

```json
{
  "type": "array",
  "prefixItems": [
    {"type": "number", "minimum": -90, "maximum": 90},
    {"type": "number", "minimum": -180, "maximum": 180}
  ],
  "items": false,
  "minItems": 2,
  "maxItems": 2
}
```

## Common Patterns

### Strict Tuple (Fixed Length)
```json
{
  "prefixItems": [
    {"type": "string"},
    {"type": "number"}
  ],
  "items": false,
  "minItems": 2,
  "maxItems": 2
}
```

### Flexible Tuple (Additional Items Allowed)
```json
{
  "prefixItems": [
    {"type": "string", "description": "Name"},
    {"type": "integer", "description": "Age"}
  ],
  "items": {"type": "string", "description": "Tags"}
}
```

### CSV-like Row
```json
{
  "prefixItems": [
    {"type": "integer", "description": "ID"},
    {"type": "string", "description": "Name"},
    {"type": "string", "format": "date", "description": "Created"}
  ],
  "items": false
}
```

## Tips

- Use descriptive schemas with descriptions for each position
- Set `items: false` for strict tuples
- Use minItems/maxItems to enforce length
- Test with JSON view to verify output
- Drag to reorder positions easily

## Keyboard Shortcuts

- **Tab**: Navigate between fields
- **Enter**: Save (when focused on button)
- **Escape**: Cancel dialog

## Related Constraints

- **minItems/maxItems**: Array length limits
- **uniqueItems**: Require unique values
- **contains**: At least one item matches schema
- **minContains/maxContains**: Control matching item count

