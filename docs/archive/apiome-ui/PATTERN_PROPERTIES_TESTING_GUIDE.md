# Pattern Properties Testing Guide

## Quick Test Steps

### 1. Start Development Server
```bash
cd /Users/kenji/Development/apiome/apiome-ui
yarn dev
```

### 2. Import Test File
1. Navigate to http://localhost:3000
2. Go to **ADE → Dashboard → Projects**
3. Click **Import** button
4. Upload `examples/openapi/03-object-properties.yaml`
5. Complete the import wizard

### 3. Open Property Editor
1. Go to **ADE → Studio**
2. Select the imported project and version
3. Find the **Configuration** class on canvas
4. Click the **settings** property (gear icon or property name)
5. Property editor dialog opens

### 4. Locate Pattern Properties Section
1. Scroll down in the property editor
2. Look for **"Object Constraints"** section (green background)
3. Inside that section, look for **"Pattern Properties"** subsection
4. Should appear after "Additional Properties" and before "Unevaluated Properties"

## Expected Result

You should see:

```
┌─ Pattern Properties ────────────────────────────┐
│ Define schemas for properties matching patterns │
│                                                  │
│ ┌─ Existing Patterns ───────────────────────┐  │
│ │ ^env_                                  [X]│  │
│ │ {                                         │  │
│ │   "type": "string",                       │  │
│ │   "description": "Environment variables   │  │
│ │                    starting with env_",   │  │
│ │   "examples": ["production"]              │  │
│ │ }                                         │  │
│ │                                           │  │
│ │ ^flag_                                 [X]│  │
│ │ {                                         │  │
│ │   "type": "boolean",                      │  │
│ │   "description": "Feature flags starting  │  │
│ │                    with flag_",           │  │
│ │   "examples": [true]                      │  │
│ │ }                                         │  │
│ └───────────────────────────────────────────┘  │
│                                                  │
│ Pattern (regex):                                 │
│ [                                             ]  │
│                                                  │
│ Schema (JSON):                                   │
│ [{ "type": "string" }                         ]  │
│ [                                             ]  │
│                                                  │
│                                            [+]   │
└──────────────────────────────────────────────────┘
```

## Debug Console Output

Open browser DevTools (F12) and check the Console tab:

### When Opening Property Editor

```javascript
[ClassPropertyEditDialog] Property name: "settings"
[ClassPropertyEditDialog] propData: {
  type: "object",
  description: "Settings object with min/max properties and pattern properties",
  minProperties: 2,
  maxProperties: 10,
  properties: {
    timeout: { type: "integer", examples: [30] },
    retries: { type: "integer", examples: [3] }
  },
  patternProperties: {
    "^env_": {
      type: "string",
      description: "Environment variables starting with env_",
      examples: ["production"]
    },
    "^flag_": {
      type: "boolean",
      description: "Feature flags starting with flag_",
      examples: [true]
    }
  },
  examples: [{ timeout: 30, retries: 3, env_mode: "production", flag_debug: false }]
}
[ClassPropertyEditDialog] schema: { ... } // Same as propData
[ClassPropertyEditDialog] baseType: "object"
[ClassPropertyEditDialog] schema.patternProperties: { "^env_": {...}, "^flag_": {...} }
```

### When Rendering Form

```javascript
[PatternProperties] data.patternProperties: {
  "^env_": {
    type: "string",
    description: "Environment variables starting with env_",
    examples: ["production"]
  },
  "^flag_": {
    type: "boolean",
    description: "Feature flags starting with flag_",
    examples: [true]
  }
}
[PatternProperties] patterns: { "^env_": {...}, "^flag_": {...} }
[PatternProperties] patternEntries: [
  ["^env_", { type: "string", description: "...", examples: [...] }],
  ["^flag_", { type: "boolean", description: "...", examples: [...] }]
]
```

## Troubleshooting

### Problem: Pattern Properties Section Not Visible

**Check 1: Is the Object Constraints section visible?**
- If NO: The property is not recognized as an object type
- Check console for `baseType` value
- Should be `"object"`, not `"string"`, `"array"`, etc.

**Check 2: Is baseType correct?**
```javascript
[ClassPropertyEditDialog] baseType: "object"  // ✅ Correct
[ClassPropertyEditDialog] baseType: "string"  // ❌ Wrong
```

**Solution if baseType is wrong:**
- The property definition in the database might be incorrect
- Check the actual property data in database
- Re-import the OpenAPI file

### Problem: Pattern Properties Section Visible but Empty

**Check 1: Are patternProperties in schema?**
```javascript
[ClassPropertyEditDialog] schema.patternProperties: undefined  // ❌ Missing
```

**Solution:**
- Pattern properties were not imported
- Check if they exist in the OpenAPI file
- Re-import the file

**Check 2: Are patternProperties passed to form?**
```javascript
[ClassPropertyEditDialog] schema.patternProperties: { ... }  // ✅ In schema
[PatternProperties] data.patternProperties: undefined  // ❌ Not in form
```

**Solution:**
- Bug in data loading useEffect in ClassPropertyEditDialog
- Check line ~217 where patternProperties is set in formData

### Problem: Console Shows No Debug Output

**Possible causes:**
1. Browser DevTools not open or Console tab not selected
2. Console filters enabled (e.g., hiding logs)
3. Page not loaded / stale cache

**Solutions:**
1. Open DevTools (F12), go to Console tab
2. Clear all console filters
3. Hard refresh (Cmd+Shift+R on Mac, Ctrl+Shift+R on Windows)
4. Clear cache and reload

### Problem: Pattern Properties Show but Can't Edit

**Check:** Are you seeing TypeScript errors in console?

**Solution:**
- Clear build cache: `rm -rf .next && yarn build`
- Restart dev server

## Testing Edit Functionality

Once pattern properties are visible:

### Test 1: Edit Existing Pattern Schema
1. Modify the JSON in the schema field
2. Click Save
3. Close and reopen property editor
4. ✅ Verify changes persisted

### Test 2: Delete Pattern
1. Click [X] button on a pattern
2. Click Save
3. Close and reopen
4. ✅ Verify pattern is removed

### Test 3: Add New Pattern
1. Enter pattern: `^test_`
2. Enter schema: `{ "type": "number" }`
3. Click [+] button
4. Click Save
5. Close and reopen
6. ✅ Verify new pattern appears

### Test 4: Generate Code
1. Go to Code view in Studio
2. Select OpenAPI Specification
3. ✅ Verify patternProperties appear in generated YAML

Expected in generated code:
```yaml
settings:
  type: object
  minProperties: 2
  maxProperties: 10
  properties:
    timeout:
      type: integer
    retries:
      type: integer
  patternProperties:
    "^env_":
      type: string
      description: Environment variables starting with env_
    "^flag_":
      type: boolean
      description: Feature flags starting with flag_
```

## Success Criteria

✅ Pattern Properties section is visible for object types
✅ Existing patterns load and display correctly
✅ Can edit pattern schemas (JSON validation)
✅ Can add new patterns
✅ Can delete patterns
✅ Changes persist after save
✅ Pattern properties appear in generated OpenAPI code
✅ Console shows expected debug output

## Clean Up

After testing is complete and working:

1. Remove debug console.log statements from:
   - `PropertyFormFields.tsx` (3 lines)
   - `ClassPropertyEditDialog.tsx` (5 lines)

2. Rebuild:
   ```bash
   yarn build
   ```

3. Verify no console spam in production

## Date
December 24, 2024

---

## Summary
This guide provides step-by-step testing instructions for the pattern properties feature, including expected console output, troubleshooting steps, and success criteria. Use this to verify that pattern properties are correctly loading, displaying, and persisting.

