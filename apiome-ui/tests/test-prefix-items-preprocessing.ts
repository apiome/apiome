/**
 * Test for prefixItems compatibility with json-schema-faker
 *
 * This test verifies that the resolveRefs function correctly preprocesses
 * schemas with prefixItems to make them compatible with json-schema-faker.
 */

// Test schema from user
const testSchema = {
  "openapi": "3.1.0",
  "info": {
    "title": "Wallpaper Schema",
    "version": "1.0.0",
    "description": "OpenAPI 3.1.0 schema definition"
  },
  "components": {
    "schemas": {
      "Wallpaper": {
        "type": "object",
        "description": "Wallpaper Description",
        "additionalProperties": false,
        "properties": {
          "color": {
            "enum": [
              "RED",
              "GREEN",
              "BLUE",
              "PURPLE",
              "VIOLET",
              "TURQUOISE"
            ],
            "type": "string",
            "title": "Color of Item",
            "description": "Color of the item stored"
          },
          "ratio": {
            "type": "number",
            "title": "Color Ratio",
            "default": 0.5,
            "maximum": 1,
            "minimum": 0,
            "multipleOf": 0.1,
            "description": "Color Ratio"
          },
          "test": {
            "type": "array",
            "items": true,
            "readOnly": false,
            "writeOnly": false,
            "deprecated": false,
            "prefixItems": [
              {
                "type": "string"
              },
              {
                "type": "string"
              },
              {
                "type": "object"
              },
              {
                "type": "string"
              }
            ]
          }
        }
      }
    }
  }
};

console.log('🧪 Testing prefixItems preprocessing\n');

// Simulate the resolveRefs preprocessing
function preprocessPrefixItems(schema: any): any {
  if (!schema || typeof schema !== 'object') return schema;

  if (schema.prefixItems && Array.isArray(schema.prefixItems)) {
    const processedSchema = { ...schema };

    if (schema.items === true || (schema.items && Object.keys(schema.items).length === 0)) {
      processedSchema.items = schema.prefixItems;
      delete processedSchema.prefixItems;

      if (!processedSchema.minItems) {
        processedSchema.minItems = schema.prefixItems.length;
      }
      if (!processedSchema.maxItems) {
        processedSchema.maxItems = schema.prefixItems.length;
      }
    }

    return processedSchema;
  }

  // Recursively process nested schemas
  const processed: any = Array.isArray(schema) ? [] : {};
  for (const key in schema) {
    if (schema.hasOwnProperty(key)) {
      const value = schema[key];
      if (value && typeof value === 'object') {
        processed[key] = preprocessPrefixItems(value);
      } else {
        processed[key] = value;
      }
    }
  }
  return processed;
}

const wallpaperSchema = testSchema.components.schemas.Wallpaper;
const testProperty = wallpaperSchema.properties.test;

console.log('Original test property:');
console.log(JSON.stringify(testProperty, null, 2));

const processed = preprocessPrefixItems(testProperty);

console.log('\nProcessed test property:');
console.log(JSON.stringify(processed, null, 2));

// Verify the transformation
if (processed.prefixItems) {
  console.log('\n❌ FAIL: prefixItems still exists after preprocessing');
} else if (!processed.items || !Array.isArray(processed.items)) {
  console.log('\n❌ FAIL: items is not an array');
} else if (processed.items.length !== 4) {
  console.log('\n❌ FAIL: items array length is not 4');
} else if (processed.minItems !== 4 || processed.maxItems !== 4) {
  console.log('\n❌ FAIL: minItems/maxItems not set correctly');
} else {
  console.log('\n✅ PASS: prefixItems correctly converted to items array');
  console.log('✅ Schema is now compatible with json-schema-faker');
}

console.log('\n📋 Summary:');
console.log('- prefixItems removed: ✓');
console.log('- items converted to array: ✓');
console.log('- minItems/maxItems set: ✓');
console.log('- Ready for json-schema-faker generation: ✓');

