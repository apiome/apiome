# OpenAPI Import - Suggested Fix Examples

This document shows practical examples of how to fix unsupported schemas using the automatically generated suggestions.

## Example 1: Simple Inline Object

### ❌ Before (Unsupported)

```json
{
  "Product": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "format": "uuid"
      },
      "name": {
        "type": "string"
      },
      "warehouse": {
        "type": "object",
        "properties": {
          "location": {
            "type": "string"
          },
          "capacity": {
            "type": "integer"
          }
        }
      }
    }
  }
}
```

### 💡 Suggestion Shown

```
Contains inline object properties: warehouse.
These properties have nested object structures that are not supported.

💡 Suggested fix:
  • Extract "warehouse" → Create "ProductWarehouse" class 
    and use $ref: "#/components/schemas/ProductWarehouse"
```

### ✅ After (Supported)

```json
{
  "Product": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "format": "uuid"
      },
      "name": {
        "type": "string"
      },
      "warehouse": {
        "$ref": "#/components/schemas/ProductWarehouse"
      }
    }
  },
  "ProductWarehouse": {
    "type": "object",
    "properties": {
      "location": {
        "type": "string"
      },
      "capacity": {
        "type": "integer"
      }
    }
  }
}
```

## Example 2: Inline Array Items

### ❌ Before (Unsupported)

```json
{
  "Order": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string"
      },
      "items": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "productId": {
              "type": "string"
            },
            "quantity": {
              "type": "integer"
            },
            "price": {
              "type": "number"
            }
          }
        }
      }
    }
  }
}
```

### 💡 Suggestion Shown

```
Contains inline object properties: items[].
These properties have nested object structures that are not supported.

💡 Suggested fix:
  • Extract "items" → Create "OrderItem" class 
    and use $ref: "#/components/schemas/OrderItem"
```

**Note**: The system automatically singularizes "items" to "Item" for the class name.

### ✅ After (Supported)

```json
{
  "Order": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string"
      },
      "items": {
        "type": "array",
        "items": {
          "$ref": "#/components/schemas/OrderItem"
        }
      }
    }
  },
  "OrderItem": {
    "type": "object",
    "properties": {
      "productId": {
        "type": "string"
      },
      "quantity": {
        "type": "integer"
      },
      "price": {
        "type": "number"
      }
    }
  }
}
```

## Example 3: Multiple Inline Objects

### ❌ Before (Unsupported)

```json
{
  "Customer": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string"
      },
      "billingAddress": {
        "type": "object",
        "properties": {
          "street": { "type": "string" },
          "city": { "type": "string" }
        }
      },
      "shippingAddress": {
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

### 💡 Suggestion Shown

```
Contains inline object properties: billingAddress, shippingAddress.
These properties have nested object structures that are not supported.

💡 Suggested fix:
  • Extract "billingAddress" → Create "CustomerBillingAddress" class 
    and use $ref: "#/components/schemas/CustomerBillingAddress"
  • Extract "shippingAddress" → Create "CustomerShippingAddress" class 
    and use $ref: "#/components/schemas/CustomerShippingAddress"
```

### ✅ After (Supported - Option 1: Separate Schemas)

```json
{
  "Customer": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string"
      },
      "billingAddress": {
        "$ref": "#/components/schemas/CustomerBillingAddress"
      },
      "shippingAddress": {
        "$ref": "#/components/schemas/CustomerShippingAddress"
      }
    }
  },
  "CustomerBillingAddress": {
    "type": "object",
    "properties": {
      "street": { "type": "string" },
      "city": { "type": "string" }
    }
  },
  "CustomerShippingAddress": {
    "type": "object",
    "properties": {
      "street": { "type": "string" },
      "city": { "type": "string" }
    }
  }
}
```

### ✅ After (Supported - Option 2: Shared Schema)

If both addresses have the same structure, you can create one shared schema:

```json
{
  "Customer": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string"
      },
      "billingAddress": {
        "$ref": "#/components/schemas/Address"
      },
      "shippingAddress": {
        "$ref": "#/components/schemas/Address"
      }
    }
  },
  "Address": {
    "type": "object",
    "properties": {
      "street": { "type": "string" },
      "city": { "type": "string" }
    }
  }
}
```

## Example 4: Nested Arrays

### ❌ Before (Unsupported)

```json
{
  "Product": {
    "type": "object",
    "properties": {
      "id": { "type": "string" },
      "variants": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "sku": { "type": "string" },
            "options": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "name": { "type": "string" },
                  "value": { "type": "string" }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

### 💡 Suggestion Shown

```
Contains inline object properties: variants[].
These properties have nested object structures that are not supported.

💡 Suggested fix:
  • Extract "variants" → Create "ProductVariant" class 
    and use $ref: "#/components/schemas/ProductVariant"
```

### ✅ After (Supported - Step 1: Extract Variants)

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
      "sku": { "type": "string" },
      "options": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": { "type": "string" },
            "value": { "type": "string" }
          }
        }
      }
    }
  }
}
```

But now `ProductVariant` also has an inline array! The system will show another suggestion:

```
Contains inline object properties: options[].

💡 Suggested fix:
  • Extract "options" → Create "ProductVariantOption" class 
    and use $ref: "#/components/schemas/ProductVariantOption"
```

### ✅ After (Supported - Step 2: Extract Options)

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
      "sku": { "type": "string" },
      "options": {
        "type": "array",
        "items": {
          "$ref": "#/components/schemas/ProductVariantOption"
        }
      }
    }
  },
  "ProductVariantOption": {
    "type": "object",
    "properties": {
      "name": { "type": "string" },
      "value": { "type": "string" }
    }
  }
}
```

## Quick Reference: Naming Patterns

| Original Property | Suggested Class Name | Notes |
|------------------|---------------------|-------|
| `Product.warehouse` | `ProductWarehouse` | Direct property |
| `Order.items[]` | `OrderItem` | Array → singular |
| `Customer.addresses[]` | `CustomerAddress` | Plural → singular |
| `User.preferences` | `UserPreference` | Plural → singular |
| `Invoice.lineItems[]` | `InvoiceLineItem` | Compound name |
| `Product.shippingInfo` | `ProductShippingInfo` | Camel case preserved |

## Tips

1. **Use the suggestion as-is**: The generated class names follow best practices
2. **Refactor if needed**: For shared structures, rename to a more generic name (e.g., `Address` instead of `CustomerAddress`)
3. **Fix recursively**: If the extracted class has inline objects, fix those too
4. **Copy-paste ready**: The `$ref` path is ready to use directly
5. **Preserve descriptions**: Remember to copy descriptions from inline objects to new schemas

## Benefits of This Approach

✅ **Cleaner schemas**: Each object type has its own definition  
✅ **Reusability**: Can reference the same schema from multiple places  
✅ **Better documentation**: Each schema can have its own description  
✅ **Easier maintenance**: Changes to a type only need to be made once  
✅ **Platform compatible**: Works with Apiome's class-based model  

## Related Documentation

- [OpenAPI Unsupported Warnings](./OPENAPI_UNSUPPORTED_WARNINGS.md)
- [OpenAPI Import Feature](./OPENAPI_IMPORT_FEATURE.md)

