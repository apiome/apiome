/**
 * Final verification test with exact user schema
 *
 * This test uses the EXACT schema provided by the user to verify
 * that the fix works for their specific use case.
 */

import jsf from 'json-schema-faker';

// Helper function to preprocess prefixItems (same as in ClassEditDialog)
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

// EXACT schema from user's report
const userSchema = {
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
            "default": "0.5",
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

console.log('🔍 Final Verification Test');
console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
console.log('Testing with EXACT schema provided by user\n');

// Extract the Wallpaper schema
const wallpaperSchema = userSchema.components.schemas.Wallpaper;

console.log('Original Schema (with prefixItems):');
console.log(JSON.stringify(wallpaperSchema, null, 2));
console.log('\n' + '─'.repeat(60) + '\n');

// Preprocess the schema
const preprocessedSchema = preprocessPrefixItems(wallpaperSchema);

console.log('Preprocessed Schema (prefixItems → items):');
console.log(JSON.stringify(preprocessedSchema, null, 2));
console.log('\n' + '─'.repeat(60) + '\n');

try {
  console.log('Generating example with json-schema-faker...\n');

  const example = jsf.generate(preprocessedSchema as any);

  console.log('✅ SUCCESS! Generated Example:');
  console.log(JSON.stringify(example, null, 2));

  console.log('\n' + '─'.repeat(60));
  console.log('\n📊 Validation Results:\n');

  let allValid = true;

  // Validate color
  const validColors = ['RED', 'GREEN', 'BLUE', 'PURPLE', 'VIOLET', 'TURQUOISE'];
  if (example.color && validColors.includes(example.color)) {
    console.log('✅ color: "' + example.color + '" (valid enum value)');
  } else {
    console.log('❌ color: Invalid value');
    allValid = false;
  }

  // Validate ratio
  if (typeof example.ratio === 'number' && example.ratio >= 0 && example.ratio <= 1) {
    const isMultipleOf01 = Math.abs((example.ratio * 10) % 1) < 0.0001;
    if (isMultipleOf01) {
      console.log('✅ ratio: ' + example.ratio + ' (valid number, multipleOf 0.1)');
    } else {
      console.log('⚠️  ratio: ' + example.ratio + ' (valid range, but not exact multipleOf 0.1)');
    }
  } else {
    console.log('❌ ratio: Invalid value');
    allValid = false;
  }

  // Validate test array
  if (Array.isArray(example.test)) {
    if (example.test.length === 4) {
      console.log('✅ test: Array with 4 items (correct length)');

      const expectedTypes = ['string', 'string', 'object', 'string'];
      let allTypesCorrect = true;

      for (let i = 0; i < example.test.length; i++) {
        const item = example.test[i];
        const expectedType = expectedTypes[i];
        const actualType = typeof item;

        if (actualType === expectedType && (expectedType !== 'object' || item !== null)) {
          console.log(`  ✅ test[${i}]: ${expectedType} ✓`);
        } else {
          console.log(`  ❌ test[${i}]: expected ${expectedType}, got ${actualType}`);
          allTypesCorrect = false;
          allValid = false;
        }
      }

      if (allTypesCorrect) {
        console.log('  ✅ All tuple items have correct types!');
      }
    } else {
      console.log('❌ test: Expected 4 items, got ' + example.test.length);
      allValid = false;
    }
  } else {
    console.log('❌ test: Not an array');
    allValid = false;
  }

  console.log('\n' + '━'.repeat(60));

  if (allValid) {
    console.log('\n🎉 ALL VALIDATIONS PASSED!');
    console.log('✅ The fix works correctly with the user\'s schema');
    console.log('✅ json-schema-faker can now handle prefixItems');
    process.exit(0);
  } else {
    console.log('\n⚠️  Some validations failed (but example was generated)');
    process.exit(1);
  }

} catch (error) {
  console.log('❌ FAILED to generate example');
  console.error('Error:', error);
  console.error('Error message:', error instanceof Error ? error.message : String(error));
  process.exit(1);
}

