# OpenAPI allOf Support Implementation

## Problem
The OpenAPI import feature was not properly handling `allOf` compositions. When schemas used `allOf` to extend base schemas (e.g., `Car` extending `Vehicle`), the properties from the referenced base schema were not being imported, resulting in classes with missing properties.

## Solution
Added support for `allOf` composition resolution in the OpenAPI import utilities by:

1. **Added `resolveReference` function**: Resolves `$ref` references to actual schema objects from the components/schemas section.

2. **Added `resolveAllOf` function**: Recursively merges all schemas in an `allOf` array into a single resolved schema by:
   - Resolving any `$ref` references within the `allOf` array
   - Recursively handling nested `allOf` compositions
   - Merging properties from all schemas
   - Merging required field arrays
   - Preserving descriptions and types appropriately

3. **Updated `parseOpenAPISpec` function**: Now calls `resolveAllOf` on each schema before processing its properties, ensuring that composition inheritance is properly flattened.

## Example
Given this OpenAPI schema:

```yaml
Vehicle:
  type: object
  required: [id, brand, model]
  properties:
    id: { type: string }
    brand: { type: string }
    model: { type: string }
    year: { type: integer }

Car:
  allOf:
    - $ref: '#/components/schemas/Vehicle'
    - type: object
      required: [numDoors]
      properties:
        numDoors: { type: integer }
        hasSunroof: { type: boolean }
```

**Before the fix**: The `Car` class would only have `numDoors` and `hasSunroof` properties.

**After the fix**: The `Car` class correctly has all properties: `id`, `brand`, `model`, `year`, `numDoors`, and `hasSunroof`, with the correct required fields: `id`, `brand`, `model`, and `numDoors`.

## Files Modified
- `/Users/kenji/Development/apiome/apiome-ui/src/app/utils/openapi-import.ts`
  - Added `resolveReference()` helper function
  - Added `resolveAllOf()` schema composition resolver
  - Modified `parseOpenAPISpec()` to resolve allOf before processing schemas

## Testing
Tested with the provided `allOf-1.yaml` example file which includes:
- A base `Vehicle` schema with common properties
- A `Car` schema extending `Vehicle` with additional properties
- A `Truck` schema extending `Vehicle` with different additional properties

All properties are now correctly imported and merged.

