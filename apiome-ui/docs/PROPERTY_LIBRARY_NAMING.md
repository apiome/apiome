# Property Library Naming and Deduplication - Fixed

## Problem
Properties were being created in `apiome.properties` with auto-generated names like `prop_0`, `prop_1`, instead of using their original meaningful names from the OpenAPI schema.

## Solution
Implemented intelligent property naming and deduplication that:

1. **Collects properties by schema definition** (JSON signature matching)
2. **Tracks all names** a property appears under across different classes
3. **Uses the first/original name** when creating the library property
4. **Reuses properties** across classes while allowing different usage names

## How It Works

### Before (Problem)
```
OpenAPI Schema:
  ProductTags:
    properties:
      name: { type: string }    ← Collected as signature
      tags: { type: array }     ← Collected as signature

Property Library Created:
  prop_0: { type: string }      ← Lost original name "name"
  prop_1: { type: array }       ← Lost original name "tags"

Class Linking:
  ProductTags.name → linked to prop_0
  ProductTags.tags → linked to prop_1
```

### After (Fixed)
```
OpenAPI Schema:
  ProductTags:
    properties:
      name: { type: string }    ← Signature + Name tracked
      tags: { type: array }     ← Signature + Name tracked
  Order:
    properties:
      name: { type: string }    ← Same signature, different class
      items: { type: array }    ← Different signature

Property Library Created:
  name: { type: string }        ← Uses original name "name"
  tags: { type: array }         ← Uses original name "tags"
  items: { type: array }        ← Uses original name "items"

Class Linking:
  ProductTags.name → linked to property "name" (reused)
  ProductTags.tags → linked to property "tags"
  Order.name → linked to property "name" (reused)
  Order.items → linked to property "items"
```

## Data Structure

The collection process now tracks:

```typescript
propertyMap: Map<signature, {
  data: any;                    // The schema definition
  description?: string;         // Description from schema
  names: Set<string>;          // All names this property appears under
}>
```

Example with the ProductTags schema:
```typescript
{
  '{"type":"string"}': {
    data: { type: "string" },
    description: undefined,
    names: Set(["name"])        // Appears as "name" in ProductTags
  },
  '{"type":"array","items":{"type":"string"}}': {
    data: { type: "array", items: { type: "string" } },
    description: "Product tags with contains validation",
    names: Set(["tags"])        // Appears as "tags" in ProductTags
  }
}
```

## Property Deduplication Logic

1. **Same signature, same class** → One library property, used once
2. **Same signature, different classes** → One library property, reused across classes
3. **Different signature** → Separate library properties

Example:
```
Schema A: { name: { type: string }, id: { type: integer } }
Schema B: { name: { type: string }, status: { type: string } }

Library Created:
  - "name" (signature: {"type":"string"}) - REUSED by A and B
  - "id" (signature: {"type":"integer"})
  - "status" (signature: {"type":"string"})
    ↑ Different property name, same type, NOT reused
```

## Class Property Usage

When linking properties to classes, the original property **usage name** is preserved:

```typescript
// ProductTags class
addPropertyToClass(
  classId,
  propertyId: "name_property_id",
  name: "name",           // ← Original usage name preserved
  description: null,
  data: { type: "string" },
  parentId: null
)

// Order class
addPropertyToClass(
  classId,
  propertyId: "name_property_id",  // ← REUSED
  name: "name",                     // ← Same name in class
  description: null,
  data: { type: "string" },
  parentId: null
)
```

## Debug Logging

The import now shows which names each property appears under:

```
DEBUG_PROPERTY: Creating property: name (used as: name)
DEBUG_PROPERTY: Creating property: tags (used as: tags, items)
DEBUG_PROPERTY: Creating property: colors (used as: colors)
```

This helps verify that properties are being named correctly and reused properly.

## Benefits

✅ **Meaningful names** - Properties keep their original schema names
✅ **Deduplication** - Same schema definitions reused across classes
✅ **Reusability** - Properties can be linked to multiple classes
✅ **Clarity** - Property library reflects actual property names from source
✅ **Maintainability** - Easy to understand which properties are reused

## Database Verification

Check that properties are named correctly:

```sql
-- View all properties created in the project
SELECT id, name, description FROM apiome.properties 
WHERE project_id = '<project-id>'
ORDER BY name;

-- Should show: name, tags, colors, etc. (not prop_0, prop_1, etc.)
```

Check that reuse works:

```sql
-- View all class properties
SELECT cp.id, cp.name, p.name as property_name, c.name as class_name
FROM apiome.class_properties cp
LEFT JOIN apiome.properties p ON cp.property_id = p.id
LEFT JOIN apiome.classes c ON cp.class_id = c.id
WHERE c.version_id = '<version-id>'
ORDER BY p.name, c.name;

-- A property name might appear in multiple classes if it's reused
```

## Files Modified

- `lib/db/import-helper.ts`
  - Updated property collection to track original names
  - Changed from auto-generated `prop_0` naming to meaningful names
  - Enhanced debug logging to show name reuse

## Testing

```bash
yarn --cwd apiome/apiome-ui dev
# Import: examples/02-array-contains.yaml
# Check Import Log for DEBUG_PROPERTY events
# Verify properties in database have meaningful names
```

Expected properties:
- `name` (type: string)
- `tags` (type: array)
- `colors` (type: array)
- NOT: `prop_0`, `prop_1`, `prop_2`

