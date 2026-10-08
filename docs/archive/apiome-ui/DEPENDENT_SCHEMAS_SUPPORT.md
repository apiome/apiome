# Dependent Schemas Support Added

## Problem Identified
Users could not edit or view `dependentSchemas` in class properties. This is a JSON Schema 2019-09+ feature for conditional validation.

## What are Dependent Schemas?
Dependent Schemas allow you to specify conditional validation rules based on the values of other properties. For example:

```yaml
Payment:
  type: object
  properties:
    paymentMethod:
      type: string
      enum: [credit_card, paypal, bank_transfer]
    cardNumber:
      type: string
  dependentSchemas:
    paymentMethod:
      if:
        properties:
          paymentMethod:
            const: "credit_card"
      then:
        required: [cardNumber, cardExpiry, cardCvv]
      else:
        # other conditions...
```

When `paymentMethod` is "credit_card", the `then` schema applies (requires card fields).

## Solution Implemented

Added complete support for viewing and editing dependent schemas in both property editors:

### 1. PropertyFormData Interface
Added field to PropertyFormFields.tsx:
```typescript
dependentSchemas?: Record<string, any>; // Map of property names to conditional schemas
```

### 2. Data Loading
**ClassPropertyEditDialog.tsx:**
```typescript
dependentSchemas: schema.dependentSchemas || undefined,
```

**PropertyDialog.tsx:**
```typescript
dependentSchemas: minMaxSource.dependentSchemas || undefined,
```

### 3. Data Saving

**ClassPropertyEditDialog.tsx:**
```typescript
if (formData.dependentSchemas && Object.keys(formData.dependentSchemas).length > 0) {
  targetSchema.dependentSchemas = formData.dependentSchemas;
} else {
  delete targetSchema.dependentSchemas;
}
```

**PropertyDialog.tsx** (array items and direct objects):
```typescript
if (formData.dependentSchemas && Object.keys(formData.dependentSchemas).length > 0) {
  dataObject.dependentSchemas = formData.dependentSchemas;
} else {
  delete dataObject.dependentSchemas;
}
```

### 4. UI Component
Added "Dependent Schemas" section to PropertyFormFields.tsx with:
- ✅ List of existing dependent schemas
- ✅ Edit each schema (5-line JSON editor)
- ✅ Delete dependent schemas
- ✅ Add new dependent schemas
- ✅ Property name input
- ✅ Schema editor with validation

## Features

✅ **View Dependent Schemas** - See all conditional schemas for a property
✅ **Edit Schemas** - Modify conditional logic with 5-line editor
✅ **Add New Schemas** - Create new conditional validations
✅ **Delete Schemas** - Remove conditional rules
✅ **Both Editors** - Works in ClassPropertyEditDialog and PropertyDialog
✅ **Full JSON Support** - Complex conditional logic with if/then/else

## UI Components Used

- Reusable `PatternPropertySchemaEditor` component (same as pattern properties)
- List display for existing dependent schemas
- IIFE pattern for add new schema form
- Consistent styling with other object constraint sections

## Building Blocks

The implementation reuses the same patterns as patternProperties:
1. **Existing Items List** - Shows current dependent schemas
2. **Delete Icon** - Remove individual schemas
3. **Schema Editor** - Edit JSON with validation
4. **Add Form** - Create new dependent schemas
5. **Helper Text** - Guidance for users

## Testing

### Manual Testing
1. Import `05-dependent-schemas.yaml`
2. Open Studio
3. Edit the "Payment" class
4. Click "settings" property (or any object with dependentSchemas)
5. Scroll to "Dependent Schemas" section
6. ✅ View existing schemas
7. ✅ Edit schemas
8. ✅ Add new schemas
9. ✅ Delete schemas

### Expected Display
```
Dependent Schemas
├── paymentMethod (existing)
│   └── {if: {...}, then: {...}, else: {...}}
└── [Add new]
    ├── Property Name: [input]
    └── Schema: [5-line editor]
```

## Build Status
✅ **Build: PASSED**
- No errors
- Only pre-existing non-blocking warnings

## Files Modified

1. **src/app/components/ade/studio/PropertyFormFields.tsx**
   - Added `dependentSchemas` to PropertyFormData interface
   - Added "Dependent Schemas" UI section (~140 lines)
   - Reused PatternPropertySchemaEditor for consistency

2. **src/app/components/ade/studio/ClassPropertyEditDialog.tsx**
   - Added dependentSchemas loading
   - Added dependentSchemas saving

3. **src/app/components/ade/studio/PropertyDialog.tsx**
   - Added dependentSchemas loading (sidebar editor)
   - Added dependentSchemas saving (array items)
   - Added dependentSchemas saving (direct objects)

## JSON Schema References

- **JSON Schema 2019-09**: Introduces dependentSchemas
- **OpenAPI 3.1**: Supports JSON Schema 2019-09 including dependentSchemas
- **Feature**: Conditional validation based on property values

## Benefits

✅ **OpenAPI 3.1 Compliance** - Full support for conditional schemas
✅ **Import Fidelity** - Imported dependent schemas are editable
✅ **Complex Logic** - Support for if/then/else conditions
✅ **Consistent UX** - Same editor patterns as other object constraints
✅ **Both Editors** - Works in main and sidebar editors

## Date
December 24, 2024

---

## Summary
Complete support for JSON Schema `dependentSchemas` has been added to both property editors. Users can now view, edit, add, and delete conditional validation rules. The implementation reuses proven patterns from pattern properties for consistency and reliability.

