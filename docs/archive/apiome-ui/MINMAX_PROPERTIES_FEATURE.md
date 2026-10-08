# MinProperties / MaxProperties Feature

## Overview
Added support for `minProperties` and `maxProperties` constraints on object types, allowing users to specify limits on the total number of properties an object can have.

## Implementation

### 1. Data Model Updates
Added two new fields to property schemas:
- `minProperties`: Minimum number of properties required in an object
- `maxProperties`: Maximum number of properties allowed in an object

### 2. UI Components Updated

#### PropertyFormFields.tsx
- Added `minProperties` and `maxProperties` to `PropertyFormData` interface
- Added UI input fields for both constraints in the "Object Constraints" section
- Fields appear only when property type is `object`
- Positioned above the "Additional Properties" radio buttons

#### PropertyDialog.tsx
- Updated `PropertyItem` interface to include `minProperties` and `maxProperties`
- Added loading logic to populate form data with existing values when editing
- Added save logic to persist values to both direct objects and array items that are objects
- Integrated with `buildPropertyJsonSchema` function

#### ClassPropertyEditDialog.tsx
- Added loading logic for `minProperties` and `maxProperties` when editing class properties
- Added save logic to persist these constraints

### 3. Property Drag & Drop
Updated `handlePropertyDrop` in `page.tsx` to ensure `minProperties` and `maxProperties` are copied when a property is dragged onto a class node on the canvas.

## Usage

### Creating a Property with Min/Max Properties
1. Open the Property Dialog (Add or Edit mode)
2. Select "object" as the property type
3. In the "Constraints" section on the right:
   - Enter a value in "Min Properties" to set the minimum number of properties (e.g., 1)
   - Enter a value in "Max Properties" to set the maximum number of properties (e.g., 10)
4. Save the property

### Example Use Cases

#### Dictionary with Size Limit
```json
{
  "type": "object",
  "minProperties": 1,
  "maxProperties": 50,
  "additionalProperties": {
    "type": "string"
  }
}
```
This creates a map/dictionary that must have at least 1 entry but no more than 50.

#### Configuration Object
```json
{
  "type": "object",
  "minProperties": 2,
  "maxProperties": 5,
  "properties": {
    "host": { "type": "string" },
    "port": { "type": "integer" }
  }
}
```
This enforces that the configuration must have at least 2 properties and at most 5.

#### Array of Objects with Size Constraints
```json
{
  "type": "array",
  "items": {
    "type": "object",
    "minProperties": 1,
    "maxProperties": 10
  }
}
```
Each object in the array must have between 1 and 10 properties.

## OpenAPI 3.1 / JSON Schema Compliance
These constraints are part of the JSON Schema specification and are fully supported in OpenAPI 3.1. They provide validation that:
- Objects with fewer properties than `minProperties` will fail validation
- Objects with more properties than `maxProperties` will fail validation

## Files Modified
1. `/src/app/components/ade/studio/PropertyFormFields.tsx`
2. `/src/app/components/ade/studio/PropertyDialog.tsx`
3. `/src/app/components/ade/studio/ClassPropertyEditDialog.tsx`
4. `/src/app/ade/studio/page.tsx`

## Testing Checklist
- [ ] Create a new property with type "object"
- [ ] Set minProperties to 2 and maxProperties to 5
- [ ] Save the property
- [ ] Drag the property onto a class node
- [ ] Verify the property is copied with minProperties and maxProperties intact
- [ ] Edit the property on the class
- [ ] Verify minProperties and maxProperties values are loaded correctly
- [ ] Modify the values and save
- [ ] Export as OpenAPI spec and verify the constraints appear in the schema
- [ ] Test with array of objects (items.minProperties and items.maxProperties)

