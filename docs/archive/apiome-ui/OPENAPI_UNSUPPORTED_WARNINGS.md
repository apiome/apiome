# OpenAPI Import - Unsupported Class Warnings

## Overview

The OpenAPI import feature now provides detailed warnings when encountering schemas that cannot be imported due to platform limitations. Unsupported classes are clearly marked and prevented from being imported.

## Unsupported Schema Types

### 1. Inline Object Properties

**Issue**: Properties that have `type: "object"` with nested `properties` defined inline.

**Example**:
```json
{
  "ProductWithInlineAddress": {
    "type": "object",
    "properties": {
      "id": { "type": "string" },
      "warehouse": {
        "type": "object",
        "properties": {
          "street": { "type": "string" },
          "city": { "type": "string" }
        }
      }
    }
  }
}
```

**Warning Message**: 
```
Contains inline object properties: warehouse. These properties have nested object structures that are not supported.

💡 Suggested fix:
  • Extract "warehouse" → Create "ProductWarehouse" class and use $ref: "#/components/schemas/ProductWarehouse"
```

**Solution**: Extract the nested object into its own schema and use `$ref` as suggested:
```json
{
  "Product": {
    "type": "object",
    "properties": {
      "id": { "type": "string" },
      "warehouse": {
        "$ref": "#/components/schemas/Warehouse"
      }
    }
  },
  "Warehouse": {
    "type": "object",
    "properties": {
      "street": { "type": "string" },
      "city": { "type": "string" }
    }
  }
}
```

### 2. Inline Array Items

**Issue**: Array properties where items have `type: "object"` with inline properties.

**Example**:
```json
{
  "ProductWithInlineVariants": {
    "type": "object",
    "properties": {
      "id": { "type": "string" },
      "variants": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "size": { "type": "string" },
            "color": { "type": "string" }
          }
        }
      }
    }
  }
}
```

**Warning Message**:
```
Contains inline object properties: variants[]. These properties have nested object structures that are not supported.

💡 Suggested fix:
  • Extract "variants" → Create "ProductVariant" class and use $ref: "#/components/schemas/ProductVariant"
```

**Solution**: Extract array items into a separate schema as suggested:
```json
{
  "Product": {
    "type": "object",
    "properties": {
      "id": { "type": "string" },
      "variants": {
        "type": "array",
        "items": {
          "$ref": "#/components/schemas/ProductVariant"
        }
      }
    }
  },
  "ProductVariant": {
    "type": "object",
    "properties": {
      "size": { "type": "string" },
      "color": { "type": "string" }
    }
  }
}
```

### 3. Unresolved References

**Issue**: `$ref` references pointing to schemas that don't exist in the specification.

**Example**:
```json
{
  "Order": {
    "type": "object",
    "properties": {
      "id": { "type": "string" },
      "customer": {
        "$ref": "#/components/schemas/Customer"
      }
    }
  }
  // Customer schema is not defined!
}
```

**Warning Message**:
```
References undefined schemas: Customer. These referenced schemas do not exist in the specification.
```

**Solution**: Add the missing schema definitions or remove the references.

## UI Behavior

### Review Step

When reviewing classes in the import wizard:

1. **Supported Classes** (shown normally):
   - White background
   - Blue border when selected
   - Checkbox enabled
   - Can be selected/deselected

2. **Unsupported Classes** (shown grayed out):
   - Gray background with 60% opacity
   - Red border
   - "Not Supported" chip badge
   - Checkbox disabled (cannot be selected)
   - Warning box showing specific issues
   - Properties still visible for reference

3. **Warning Summary** (bottom of review step):
   - Yellow alert box with count of unsupported classes
   - Scrollable list with class name and short reason
   - Clean, formatted display (not run-on sentence)
   - Links to detailed warnings on each class above

### Example Display

**Warning Summary (at bottom of review step)**:
```
⚠️ 2 classes cannot be imported

The following classes have issues that prevent them from being imported:

┌─────────────────────────────────────────────┐
│ ProductWithInlineAddress                     │
│ Contains inline object properties: warehouse.│
├─────────────────────────────────────────────┤
│ OrderWithMissingRef                          │
│ References undefined schemas: NonExistent... │
└─────────────────────────────────────────────┘

Detailed warnings are shown on each unsupported class above.
```

## Implementation Details

### Data Structure Changes

**ParsedClass Interface**:
```typescript
export interface ParsedClass {
  name: string;
  description?: string;
  properties: ParsedProperty[];
  selected: boolean;
  warnings: string[];      // NEW: Array of warning messages
  isSupported: boolean;    // NEW: Whether class can be imported
}
```

**OpenAPIParseResult Interface**:
```typescript
export interface OpenAPIParseResult {
  success: boolean;
  classes: ParsedClass[];
  error?: string;
  warnings: string[];      // NEW: Global warnings array
  version?: string;
  title?: string;
  description?: string;
}
```

### Validation Functions

1. **`findInlineObjectProperties(schema)`**
   - Scans schema properties for inline objects
   - Returns array of property names with issues
   - Checks both direct properties and array items

2. **`extractReferences(obj, refs)`**
   - Recursively finds all `$ref` in schema
   - Returns Set of referenced schema names
   - Extracts name from `#/components/schemas/Name` format

3. **`findUnresolvedReferences(schema, allSchemaNames)`**
   - Compares references against available schemas
   - Returns array of missing schema names
   - Validates references point to existing definitions

### Selection Logic

```typescript
const toggleClassSelection = (index: number) => {
  const cls = updatedClasses[index];
  
  // Prevent selecting unsupported classes
  if (!cls.isSupported) {
    return; // No-op if unsupported
  }
  
  // Toggle selection for supported classes
  updatedClasses[index].selected = !updatedClasses[index].selected;
};
```

## Testing

### Test File

Use `docs/test-openapi-unsupported.json` which includes:

**Supported Classes** (3):
- ✅ ValidProduct - Basic properties only
- ✅ ValidCustomer - Uses proper `$ref`
- ✅ Address - Referenced by ValidCustomer

**Unsupported Classes** (4):
- ❌ InvalidProductWithInlineAddress - Inline warehouse object
- ❌ InvalidProductWithInlineArrayItems - Inline array items
- ❌ InvalidOrderWithMissingRef - References NonExistentCustomer, NonExistentOrderItem
- ❌ InvalidMixedProblems - Both inline objects AND missing refs

### Expected Behavior

1. Upload `test-openapi-unsupported.json`
2. See warning alert at top listing 4 unsupported classes
3. 3 classes selectable (ValidProduct, ValidCustomer, Address)
4. 4 classes grayed out with specific warnings
5. Cannot check checkboxes for unsupported classes
6. Can proceed with only supported classes

### Manual Testing Steps

1. **Test inline object detection**:
   - Upload test file
   - Verify "InvalidProductWithInlineAddress" shows warning about "warehouse"
   - Verify "InvalidProductWithInlineArrayItems" shows warning about "variants[]"

2. **Test unresolved reference detection**:
   - Verify "InvalidOrderWithMissingRef" shows warning about missing schemas
   - Verify specific schema names are listed

3. **Test multiple issues**:
   - Verify "InvalidMixedProblems" shows warnings for both issues

4. **Test selection prevention**:
   - Try clicking checkbox on unsupported class
   - Verify it cannot be selected
   - Verify supported classes can still be selected

5. **Test import**:
   - Select only supported classes
   - Import project
   - Verify only 3 classes created in database

## Error Messages Reference

| Issue | Property Format | Message |
|-------|----------------|---------|
| Inline object | `warehouse` | Contains inline object properties: warehouse. These properties have nested object structures that are not supported.<br><br>💡 Suggested fix:<br>  • Extract "warehouse" → Create "ProductWarehouse" class and use $ref: "#/components/schemas/ProductWarehouse" |
| Inline array items | `variants[]` | Contains inline object properties: variants[]. These properties have nested object structures that are not supported.<br><br>💡 Suggested fix:<br>  • Extract "variants" → Create "ProductVariant" class and use $ref: "#/components/schemas/ProductVariant" |
| Missing single ref | `customer` | References undefined schemas: Customer. These referenced schemas do not exist in the specification. |
| Missing multiple refs | `customer`, `items` | References undefined schemas: Customer, OrderItem. These referenced schemas do not exist in the specification. |
| Combined issues | - | Multiple warnings shown with suggestions for each issue |

## Suggested Class Names

When inline object properties are detected, the system automatically suggests class names following this pattern:

**Pattern**: `{ParentClassName}{PropertyName}`

**Examples**:
- `Product.warehouse` → Suggested class: `ProductWarehouse`
- `Order.shippingAddress` → Suggested class: `OrderShippingAddress`
- `Customer.billingInfo` → Suggested class: `CustomerBillingInfo`
- `Product.variants[]` → Suggested class: `ProductVariant` (singular)

**Naming Rules**:
1. Property name is capitalized
2. Plural property names are singularized (variants → Variant)
3. Parent class name is prepended
4. Array properties use singular form for the class name

## Benefits

1. **Clear Communication**: Users understand exactly why classes can't be imported
2. **Actionable Feedback**: Specific property/reference names help fix issues
3. **Automated Suggestions**: System suggests class names following best practices
4. **Time Saving**: No need to figure out naming conventions
5. **Safety**: Prevents importing broken schemas
6. **Transparency**: Shows all classes including unsupported ones
7. **Guidance**: Explains what needs to be fixed in the spec with concrete examples

## Future Enhancements

Potential improvements:
1. Auto-fix suggestions (e.g., "Extract to new schema")
2. Preview of how to restructure the schema
3. Option to skip problematic properties instead of entire class
4. Link to documentation on schema best practices
5. Export modified spec with issues fixed

## Related Documentation

- [OpenAPI Import Feature](./OPENAPI_IMPORT_FEATURE.md)
- [Property Name Validation](./PROPERTY_NAME_VALIDATION.md)
- [Class Name Validation](./CLASS_NAME_VALIDATION.md)

