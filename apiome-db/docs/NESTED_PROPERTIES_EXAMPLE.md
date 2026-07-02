# Nested Properties Example

## Database Structure Example

Here's how nested properties are stored in the `class_properties` table:

```
class_properties table:
+--------------------------------------+----------+-------------+----------------+-------------+
| id                                   | class_id | property_id | name           | parent_id   |
+--------------------------------------+----------+-------------+----------------+-------------+
| prop-1                              | class-a  | type-uuid   | id             | NULL        |
| prop-2                              | class-a  | type-string | name           | NULL        |
| prop-3                              | class-a  | type-object | address        | NULL        |
| prop-4                              | class-a  | type-string | street         | prop-3      |
| prop-5                              | class-a  | type-string | city           | prop-3      |
| prop-6                              | class-a  | type-string | zipCode        | prop-3      |
| prop-7                              | class-a  | type-object | coordinates    | prop-3      |
| prop-8                              | class-a  | type-number | latitude       | prop-7      |
| prop-9                              | class-a  | type-number | longitude      | prop-7      |
+--------------------------------------+----------+-------------+----------------+-------------+
```

## Hierarchical Representation

```
User Class
├── id (UUID)                    [parent_id: NULL]
├── name (string)                [parent_id: NULL]
└── address (object)             [parent_id: NULL]
    ├── street (string)          [parent_id: prop-3]
    ├── city (string)            [parent_id: prop-3]
    ├── zipCode (string)         [parent_id: prop-3]
    └── coordinates (object)     [parent_id: prop-3]
        ├── latitude (number)    [parent_id: prop-7]
        └── longitude (number)   [parent_id: prop-7]
```

## JSON Schema Output

When the above structure is converted to JSON Schema:

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid"
    },
    "name": {
      "type": "string"
    },
    "address": {
      "type": "object",
      "properties": {
        "street": {
          "type": "string"
        },
        "city": {
          "type": "string"
        },
        "zipCode": {
          "type": "string"
        },
        "coordinates": {
          "type": "object",
          "properties": {
            "latitude": {
              "type": "number"
            },
            "longitude": {
              "type": "number"
            }
          }
        }
      }
    }
  }
}
```

## SQL Queries

### Get All Properties for a Class (Hierarchical Order)

```sql
SELECT 
  cp.id, 
  cp.class_id, 
  cp.property_id, 
  cp.name, 
  cp.description, 
  cp.data, 
  cp.parent_id,
  p.id as property_source_id, 
  p.name as property_source_name
FROM apiome.class_properties cp
LEFT JOIN apiome.properties p ON cp.property_id = p.id
WHERE cp.class_id = 'class-a'
ORDER BY cp.parent_id NULLS FIRST, cp.name ASC;
```

Result order:
1. Top-level properties (parent_id IS NULL)
2. First-level children (grouped by parent)
3. Second-level children (grouped by parent)
4. And so on...

### Get Only Top-Level Properties

```sql
SELECT *
FROM apiome.class_properties
WHERE class_id = 'class-a' 
  AND parent_id IS NULL
ORDER BY name ASC;
```

### Get Children of a Specific Property

```sql
SELECT *
FROM apiome.class_properties
WHERE class_id = 'class-a' 
  AND parent_id = 'prop-3'
ORDER BY name ASC;
```

### Recursive Query to Get Full Property Tree

```sql
WITH RECURSIVE property_tree AS (
  -- Base case: top-level properties
  SELECT 
    id, 
    class_id, 
    property_id, 
    name, 
    description, 
    data, 
    parent_id,
    0 as level,
    name::text as path
  FROM apiome.class_properties
  WHERE class_id = 'class-a' AND parent_id IS NULL
  
  UNION ALL
  
  -- Recursive case: child properties
  SELECT 
    cp.id, 
    cp.class_id, 
    cp.property_id, 
    cp.name, 
    cp.description, 
    cp.data, 
    cp.parent_id,
    pt.level + 1,
    pt.path || '.' || cp.name
  FROM apiome.class_properties cp
  INNER JOIN property_tree pt ON cp.parent_id = pt.id
)
SELECT * FROM property_tree
ORDER BY path;
```

Result includes full path like:
- `address`
- `address.city`
- `address.coordinates`
- `address.coordinates.latitude`
- `address.coordinates.longitude`
- `address.street`
- `address.zipCode`
- `id`
- `name`

## Constraint Behavior

### Uniqueness

Property names must be unique within the same parent scope:

✅ **ALLOWED:**
```
class-a → name (parent_id: NULL)
class-a → address (parent_id: NULL)
class-a → name (parent_id: address)  // Different level, OK!
```

❌ **NOT ALLOWED:**
```
class-a → name (parent_id: NULL)
class-a → name (parent_id: NULL)  // Duplicate at same level
```

❌ **NOT ALLOWED:**
```
class-a → address → street (parent_id: address)
class-a → address → street (parent_id: address)  // Duplicate child
```

### Cascade Deletion

When a parent property is deleted, all child properties are automatically deleted:

```sql
DELETE FROM apiome.class_properties WHERE id = 'prop-3';
-- Automatically deletes: prop-4, prop-5, prop-6, prop-7, prop-8, prop-9
```

## Application Code Examples

### TypeScript: Creating Nested Structure

```typescript
// 1. Create the parent object property
const addressResult = await addPropertyToClass(
  classId,
  objectTypePropertyId,
  'address',
  'User address',
  { type: 'object' },
  null  // No parent - top level
);

const addressId = JSON.parse(addressResult).classProperty.id;

// 2. Create child properties
await addPropertyToClass(
  classId,
  stringTypePropertyId,
  'street',
  null,
  { type: 'string' },
  addressId  // Parent is address
);

await addPropertyToClass(
  classId,
  stringTypePropertyId,
  'city',
  null,
  { type: 'string' },
  addressId
);

// 3. Create nested object
const coordsResult = await addPropertyToClass(
  classId,
  objectTypePropertyId,
  'coordinates',
  null,
  { type: 'object' },
  addressId  // Parent is address
);

const coordsId = JSON.parse(coordsResult).classProperty.id;

// 4. Create deeply nested properties
await addPropertyToClass(
  classId,
  numberTypePropertyId,
  'latitude',
  null,
  { type: 'number' },
  coordsId  // Parent is coordinates
);

await addPropertyToClass(
  classId,
  numberTypePropertyId,
  'longitude',
  null,
  { type: 'number' },
  coordsId
);
```

### TypeScript: Building Property Tree

```typescript
interface PropertyNode {
  id: string;
  name: string;
  data: any;
  children: PropertyNode[];
}

function buildPropertyTree(properties: any[]): PropertyNode[] {
  const map = new Map<string, PropertyNode>();
  const roots: PropertyNode[] = [];
  
  // Create nodes
  properties.forEach(prop => {
    map.set(prop.id, {
      id: prop.id,
      name: prop.name,
      data: prop.data,
      children: []
    });
  });
  
  // Build tree
  properties.forEach(prop => {
    const node = map.get(prop.id)!;
    if (prop.parent_id === null) {
      roots.push(node);
    } else {
      const parent = map.get(prop.parent_id);
      if (parent) {
        parent.children.push(node);
      }
    }
  });
  
  return roots;
}

// Usage
const propertiesJson = await getPropertiesForClass(classId);
const properties = JSON.parse(propertiesJson);
const tree = buildPropertyTree(properties);
```

## Best Practices

1. **Limit Nesting Depth**: Keep nesting to 2-3 levels for maintainability
2. **Use Descriptive Names**: Make property paths clear (e.g., `address.coordinates.latitude`)
3. **Validate Types**: Ensure only "object" type properties have children
4. **Document Structure**: Maintain documentation of complex nested structures
5. **Consider Performance**: Deep nesting may impact query performance for large datasets
6. **Test Cascade Deletes**: Verify deletion behavior in development before production use

