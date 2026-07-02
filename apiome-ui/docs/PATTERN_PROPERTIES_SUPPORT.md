# Pattern Properties Support Added

## Problem
When importing OpenAPI specifications that use `patternProperties` (e.g., `03-object-properties.yaml`), the pattern properties were not visible in the "Edit Property in Class" form. Users could not view or edit pattern properties that were imported from the specification.

## What are Pattern Properties?
Pattern Properties are part of JSON Schema (and OpenAPI 3.1) that allow you to define schemas for object properties that match specific regular expression patterns. This is useful for:

- Environment variables (e.g., `^env_` pattern)
- Feature flags (e.g., `^flag_` pattern)
- Dynamic property names following a convention
- Validating property values based on their names

### Example
```yaml
settings:
  type: object
  patternProperties:
    "^env_":
      type: string
      description: Environment variables starting with env_
    "^flag_":
      type: boolean
      description: Feature flags starting with flag_
```

This means any property starting with `env_` must be a string, and any property starting with `flag_` must be a boolean.

## Solution Implemented

Added complete support for viewing and editing pattern properties in the property form.

### 1. Added to Interface

**File:** `PropertyFormFields.tsx`

```typescript
export interface PropertyFormData {
  // ...existing fields
  patternProperties?: Record<string, any>; // Map of regex patterns to schemas
  // ...
}
```

### 2. Added UI Component

**Location:** After "Additional Properties" section, before "Unevaluated Properties"

**Features:**
- ✅ View existing pattern properties with their patterns and schemas
- ✅ Edit JSON schemas for each pattern
- ✅ Add new pattern properties with regex patterns
- ✅ Delete pattern properties
- ✅ JSON validation for schemas
- ✅ Example hint for users

**UI Elements:**
- Pattern input field (with monospace font for regex)
- Schema JSON editor (multiline, monospace)
- Add button (disabled until pattern is entered)
- Delete button for each pattern
- Example tooltip

### 3. Data Loading

**File:** `ClassPropertyEditDialog.tsx`

Added pattern properties extraction when loading a property for editing:

```typescript
patternProperties: schema.patternProperties || undefined,
```

### 4. Data Saving

**File:** `ClassPropertyEditDialog.tsx`

Added pattern properties serialization when saving:

```typescript
// Handle patternProperties
if (formData.patternProperties && Object.keys(formData.patternProperties).length > 0) {
  targetSchema.patternProperties = formData.patternProperties;
} else {
  delete targetSchema.patternProperties;
}
```

## UI Preview

```
┌─ Pattern Properties ─────────────────────────────────┐
│ Define schemas for properties matching patterns      │
│                                                       │
│ ┌─ Existing Patterns ────────────────────────────┐  │
│ │ ^env_                                       [X]│  │
│ │ { "type": "string", "description": "..." }    │  │
│ │                                                 │  │
│ │ ^flag_                                      [X]│  │
│ │ { "type": "boolean" }                          │  │
│ └─────────────────────────────────────────────────┘  │
│                                                       │
│ Pattern (regex):                                      │
│ [                                                  ]  │
│                                                       │
│ Schema (JSON):                                        │
│ [{ "type": "string" }                              ]  │
│ [                                                  ]  │
│                                                       │
│                                              [+]      │
│                                                       │
│ Example: Pattern ^env_ with schema                   │
│ {"type":"string"} validates any property             │
│ starting with "env_" as a string.                    │
└───────────────────────────────────────────────────────┘
```

## Testing

### Import Test
1. Import `examples/openapi/03-object-properties.yaml`
2. Open the "Configuration" class
3. Click on the "settings" property
4. Scroll to "Pattern Properties" section
5. ✅ Verify you see `^env_` and `^flag_` patterns
6. ✅ Verify schemas are displayed correctly

### Edit Test
1. Edit an existing pattern schema
2. Save the property
3. Reopen the property
4. ✅ Verify changes persisted

### Add Test
1. Enter a new pattern: `^feature_`
2. Enter schema: `{ "type": "string", "enum": ["on", "off"] }`
3. Click [+] button
4. Save the property
5. ✅ Verify new pattern appears in list

### Delete Test
1. Click [X] on a pattern
2. Save the property
3. ✅ Verify pattern is removed

### Code View Test
1. Switch to Code view in Studio
2. Generate OpenAPI spec
3. ✅ Verify patternProperties appear in generated YAML/JSON

## Build Status
✅ **Build: PASSED**
- No TypeScript errors
- Only non-blocking MUI deprecation warnings

## Files Modified

1. **src/app/components/ade/studio/PropertyFormFields.tsx**
   - Added `patternProperties` to PropertyFormData interface
   - Added Pattern Properties UI section (lines ~1730-1920)
   - Includes pattern list, add/edit/delete functionality

2. **src/app/components/ade/studio/ClassPropertyEditDialog.tsx**
   - Added pattern properties loading (line ~215)
   - Added pattern properties saving (lines ~361-366)

## Related Standards

- **JSON Schema**: `patternProperties` is part of JSON Schema Draft 4+
- **OpenAPI 3.1**: Fully supports JSON Schema including `patternProperties`
- **Validation**: Pattern properties work alongside:
  - `properties` - explicitly named properties
  - `additionalProperties` - catch-all for other properties
  - `unevaluatedProperties` - for composition scenarios

## Example Usage

### Environment Configuration
```yaml
Config:
  type: object
  properties:
    name:
      type: string
  patternProperties:
    "^env_":
      type: string
      description: Environment variables
```
Valid: `{ name: "prod", env_host: "localhost", env_port: "8080" }`

### Feature Flags
```yaml
Settings:
  type: object
  patternProperties:
    "^flag_":
      type: boolean
    "^limit_":
      type: integer
      minimum: 0
```
Valid: `{ flag_darkMode: true, flag_beta: false, limit_requests: 100 }`

## Benefits

✅ **Complete OpenAPI 3.1 Support**: Handle all pattern property definitions
✅ **Import Fidelity**: Preserve pattern properties from imported specs
✅ **Visual Editing**: No need to edit raw JSON
✅ **Validation**: Ensure schemas are valid JSON
✅ **User-Friendly**: Clear labels and examples

## Date
December 24, 2024

---

## Summary
Pattern Properties support has been added to the property editing form. Users can now view, edit, add, and delete pattern properties when working with object types. This completes support for OpenAPI 3.1 pattern property definitions and ensures imported specifications maintain full fidelity.

