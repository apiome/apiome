# Class Property Constraints Feature

## Overview
When editing a property that is a member of a class, the Class Property Edit Dialog now supports editing constraints while keeping the type and base type read-only.

## Changes Made

### Modified File
- `src/app/components/ade/studio/ClassPropertyEditDialog.tsx`

## Features Added

### 1. Read-Only Type Display
- Added an informational banner explaining that type and base type cannot be modified
- Displays the property type as a read-only chip badge
- Shows if the property references another class

### 2. String Constraints
For properties of type `string`:
- **Min Length**: Minimum string length
- **Max Length**: Maximum string length
- **Pattern**: Regular expression pattern for validation
- **Format**: String format (date, date-time, email, uri, uuid, etc.)

### 3. Number Constraints
For properties of type `number` or `integer`:
- **Minimum**: Minimum numeric value
  - Option to make it exclusive (value > minimum instead of value >= minimum)
- **Maximum**: Maximum numeric value
  - Option to make it exclusive (value < maximum instead of value <= maximum)
- **Multiple Of**: Value must be a multiple of this number

### 4. Array Constraints
For array properties:
- **Min Items**: Minimum number of items in the array
- **Max Items**: Maximum number of items in the array
- **Unique Items**: Checkbox to require all items to be unique

### 5. Enum Values
For string, number, and integer types:
- Add/remove allowed enum values
- Input field with "Add" button or Enter key to add values
- List view of current enum values with delete buttons

### 6. Default Value
- Text field to specify a default value
- Supports JSON format for complex types

### 7. Example Value
- Existing field for providing example values (JSON format)

## User Experience

### Dialog Layout
1. **Info Banner**: Explains that type is read-only
2. **Type Display**: Shows property type in a chip
3. **Property Name**: Editable text field
4. **Description**: Editable multiline text field
5. **OpenAPI Extensions**: Required, Deprecated, ReadOnly, WriteOnly checkboxes
6. **Object Settings**: Additional Properties options (for object types)
7. **Constraints**: Type-specific constraint fields
8. **Example Value**: JSON example

### Constraint Visibility
- Constraints are only shown for applicable types
- Reference types (properties with $ref) don't show constraints
- Array constraints appear in addition to item type constraints

## Implementation Details

### State Management
Added state variables for all constraint fields:
- String: minLength, maxLength, pattern, format
- Number: minimum, maximum, exclusiveMinimum, exclusiveMaximum, multipleOf
- Array: minItems, maxItems, uniqueItems
- Common: default, enum[]

### Data Handling
- Constraints are loaded from the property's data schema
- For array types, constraints are applied to the items schema (except array-specific ones)
- Constraints are saved back to the appropriate schema location
- Empty/cleared constraints are removed from the schema

### Helper Functions
- `getPropertyTypeInfo()`: Extracts type information from property data
- `handleAddEnum()`: Adds a value to the enum list
- `handleRemoveEnum()`: Removes a value from the enum list

## Usage

1. Open a class node in the canvas
2. Click the edit button on any property
3. The dialog opens showing the property type (read-only)
4. Edit the property name, description, and any applicable constraints
5. Click "Save" to update the property

## Technical Notes

- Type and base type are determined from the property's data schema
- Array types show both array-level constraints and item-level constraints
- The dialog automatically detects the property type and shows relevant constraint fields
- All constraint values are validated before saving
- JSON Schema conventions are followed for constraint naming and behavior

