# OpenAPI allOf/anyOf/oneOf - Complete Fix Summary

## The Real Problem

When importing OpenAPI schemas with `allOf` compositions, three things were going wrong:

### Problem 1: Storing Too Many Properties
**What was happening:**
```yaml
# Import this:
Car:
  allOf:
    - $ref: '#/components/schemas/Vehicle'  # Has: id, brand, model, year
    - type: object
      properties:
        numDoors: { type: integer }
        hasSunroof: { type: boolean }
```

**Old behavior:** Stored ALL 6 properties in class_properties table (id, brand, model, year, numDoors, hasSunroof)

**Problem:** When exporting, we'd get:
```yaml
Car:
  allOf: [...]
  properties:        # ❌ Wrong! Properties appear twice
    id: ...          # Once in Vehicle reference
    brand: ...       # And again at root level
    model: ...
    year: ...
    numDoors: ...
    hasSunroof: ...
```

**Fix:** Only store DIRECT properties (numDoors, hasSunroof). Let the allOf reference handle Vehicle properties.

### Problem 2: Overwriting allOf Structure on Export
**What was happening:**
```typescript
// buildClassSchema was doing:
const classSchema = {
  type: 'object',              // ❌ This overwrites allOf!
  ...schemaWithoutProperties,  // allOf is here but gets overwritten
  properties: ...              // Adding properties at wrong level
}
```

**Problem:** The `type: 'object'` at the beginning overwrites the `allOf` that comes later in the spread.

**Fix:** Check for compositions first, and if present, don't add `type: 'object'` or root-level properties.

### Problem 3: Property-Level Compositions Not Displayed
**What was happening:**
```yaml
roles:
  anyOf:
    - $ref: '#/components/schemas/Developer'
    - $ref: '#/components/schemas/Manager'
```

**Old display:** `roles: object` (generic, no indication of constraint)

**Fix:** Detect anyOf/oneOf/allOf in property data and display as `anyOf(Developer | Manager)`

## The Complete Solution

### 1. Import: Extract Only Direct Properties
```typescript
function extractDirectProperties(schema) {
  // For allOf schemas, skip $ref items (inherited properties)
  // Only return properties from inline object definitions
  if (schema.allOf) {
    for (const item of schema.allOf) {
      if (item.$ref) continue;  // ✅ Skip inherited properties
      // ... merge only inline properties
    }
  }
  return { properties, required };
}
```

**Result:**
- Vehicle class: Stores id, brand, model, year
- Car class: Stores ONLY numDoors, hasSunroof (NOT the Vehicle properties)

### 2. Export: Preserve Composition Structure
```typescript
function buildClassSchema(classData) {
  const hasComposition = schema.allOf || schema.anyOf || schema.oneOf;
  
  if (hasComposition) {
    // ✅ Return schema with composition intact
    return {
      ...schemaWithoutProperties  // Contains allOf/anyOf/oneOf
      // NO type: object
      // NO root-level properties
    };
  } else {
    // Normal schema
    return {
      type: 'object',
      properties: ...,
      required: ...
    };
  }
}
```

**Result:**
```yaml
Car:
  allOf:                    # ✅ Preserved from original import
    - $ref: '#/components/schemas/Vehicle'
    - type: object
      properties:
        numDoors: ...       # ✅ Only direct properties
        hasSunroof: ...
```

### 3. Display: Show Composition Types
```typescript
function getPropertyType(prop) {
  if (d?.anyOf) {
    const types = d.anyOf.map(item => 
      item.$ref ? item.$ref.split('/').pop() : item.type
    );
    return `anyOf(${types.join(' | ')})`;
  }
  // ... similar for allOf and oneOf
}
```

**Result:** `roles: anyOf(Developer | Manager)` instead of `roles: object`

## What Gets Stored Where

### Database Schema

**classes table:**
```sql
schema (JSONB):
{
  "allOf": [
    { "$ref": "#/components/schemas/Vehicle" },
    {
      "type": "object",
      "properties": {
        "numDoors": { "type": "integer" },
        "hasSunroof": { "type": "boolean" }
      }
    }
  ]
}
```

**class_properties table:**
```sql
class_id | name       | data
---------|------------|------------------
car_id   | numDoors   | {"type":"integer"}
car_id   | hasSunroof | {"type":"boolean"}
-- ✅ Vehicle properties (id, brand, model, year) are NOT stored here
```

## Import → Storage → Export Flow

### Import Phase
1. Parse OpenAPI file
2. Detect `Car` has `allOf`
3. **Store original schema** with allOf in `classes.schema`
4. **Extract only direct properties** (numDoors, hasSunroof)
5. Store direct properties in `class_properties`

### Storage
- `classes.schema`: `{ allOf: [...] }` ✅
- `class_properties`: numDoors, hasSunroof ✅

### Export Phase
1. Load `classes.schema` → Contains allOf structure
2. Check: Has composition? YES
3. Return schema as-is (preserving allOf)
4. Result: Exported OpenAPI matches original structure ✅

## Test Results

### allOf-1.yaml (Vehicle/Car/Truck)
✅ Vehicle: 4 direct properties stored  
✅ Car: 2 direct properties stored (NOT 6)  
✅ Export preserves allOf structure  
✅ Class node shows blue handle for allOf

### allOf-3.yaml (Employee with anyOf roles)
✅ Person: 4 direct properties stored  
✅ Employee: 4 direct properties stored (NOT 8)  
✅ roles property: anyOf preserved in data  
✅ Display shows: `roles: anyOf(Developer | Manager)`  
✅ Export preserves allOf structure

## Files Modified

1. **openapi-import.ts**
   - Added `extractDirectProperties()` - Filters out inherited properties
   - Modified `parseOpenAPISpec()` - Uses direct properties only
   - Preserves original schema with compositions

2. **openapi.ts**
   - Modified `buildClassSchema()` - Detects compositions, doesn't overwrite
   - Preserves allOf/anyOf/oneOf structure on export

3. **ClassNode.tsx**
   - Modified `getPropertyType()` - Displays composition types nicely

4. **helper.ts**
   - Modified `importProjectFromOpenAPI()` - Uses class.schema instead of hardcoding

## Key Takeaways

1. **Don't store inherited properties** - Only store what's directly defined
2. **Preserve original schema** - Keep allOf structure intact in database
3. **Check for compositions** - Don't add `type: object` to composition schemas
4. **Display compositions** - Show anyOf/oneOf/allOf in property types

## Before vs After

### Before
```
Import: Car with allOf → Store 6 properties ❌
Export: Car with type: object + 6 properties ❌ (allOf lost)
Display: roles as "object" ❌ (anyOf lost)
```

### After
```
Import: Car with allOf → Store 2 direct properties ✅
Export: Car with allOf + 2 direct properties ✅ (structure preserved)
Display: roles as "anyOf(Developer | Manager)" ✅ (composition shown)
```

## Result: Perfect Round-Trip

Import OpenAPI → Store → Export → **Identical Structure** ✅

