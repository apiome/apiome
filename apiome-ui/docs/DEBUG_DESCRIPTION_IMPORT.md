# Debugging Description Import Issue

## Example File Analysis

The example file `02-array-contains.yaml` has the ProductTags schema with these properties:
- `name`: type string - **HAS DESCRIPTION**: "NOT PROVIDED IN EXAMPLE" (no description field shown)
- `tags`: type array - **HAS DESCRIPTION**: "Product tags with contains validation"
- `colors`: type array - **HAS DESCRIPTION**: "Available colors"

## Expected Flow

1. **OpenAPI Importer (openapi.ts)**
   - `convertProperty()` extracts `propSchema.description` 
   - Stores in `NormalizedProperty.description`
   - Should preserve all descriptions from source schema

2. **Property Deduplication (import-helper.ts)**
   - `collectProperties()` iterates through normalized properties
   - Stores description in propertyMap: `{ data: p.data, description: p.description }`
   - Creates map of unique property signatures

3. **Property Library Creation (import-helper.ts)**
   - For each unique property, calls `createProperty()`
   - **PASSES**: `payload.description || null`
   - Should store description in database

4. **Class Property Linking (import-helper.ts)**
   - `writeClassWithProperties()` looks up property ID from map
   - Calls `addPropertyToClass(classId, propertyId, p.name, p.description || null, p.data, parentId)`
   - **KEY POINT**: `p.description` is the original normalized property's description

## Potential Issues

1. ✅ FIXED: Description extraction in importer (simplified to just use `description` field)
2. ✅ Description storage in propertyMap during deduplication
3. ✅ Description passing to createProperty() in library
4. ✅ Description preservation when linking to class properties

## Debug Events Added

When importing, look for these events in the Import Log:

- `DEBUG_PROPERTY`: Shows description being created in library
- `DEBUG_PROPERTY_CREATED`: Confirms property creation
- `DEBUG_CLASS_PROPERTY`: Shows description being linked to class

## Verification Queries

To verify descriptions are being imported:

1. In database, check `apiome.properties` table for the created properties
   - Look at the `description` column
   
2. In database, check `apiome.class_properties` table
   - Look at the `description` column for each property linked to a class

## Next Steps

Run an import with the example file and:
1. Check Import Log for DEBUG events
2. Verify descriptions in database
3. If descriptions are missing, check which DEBUG event is the last one fired

