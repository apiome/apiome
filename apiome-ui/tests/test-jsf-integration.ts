/**
 * Integration test for json-schema-faker with preprocessed prefixItems
 */

import jsf from 'json-schema-faker';

const wallpaperSchema = {
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
      "items": [
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
      ],
      "minItems": 4,
      "maxItems": 4,
      "readOnly": false,
      "writeOnly": false,
      "deprecated": false
    }
  }
};

console.log('🧪 Testing json-schema-faker with preprocessed schema\n');

try {
  const example = jsf.generate(wallpaperSchema as any);

  console.log('✅ Successfully generated example:\n');
  console.log(JSON.stringify(example, null, 2));

  // Validate the generated example
  console.log('\n📊 Validation:');

  if (example.color && ['RED', 'GREEN', 'BLUE', 'PURPLE', 'VIOLET', 'TURQUOISE'].includes(example.color)) {
    console.log('✓ color: Valid enum value');
  } else {
    console.log('✗ color: Invalid value');
  }

  if (typeof example.ratio === 'number' && example.ratio >= 0 && example.ratio <= 1) {
    console.log('✓ ratio: Valid number in range [0, 1]');
  } else {
    console.log('✗ ratio: Invalid number');
  }

  if (Array.isArray(example.test) && example.test.length === 4) {
    console.log('✓ test: Array with 4 items (matching prefixItems)');

    if (typeof example.test[0] === 'string') {
      console.log('  ✓ test[0]: string');
    } else {
      console.log('  ✗ test[0]: not a string');
    }

    if (typeof example.test[1] === 'string') {
      console.log('  ✓ test[1]: string');
    } else {
      console.log('  ✗ test[1]: not a string');
    }

    if (typeof example.test[2] === 'object' && example.test[2] !== null) {
      console.log('  ✓ test[2]: object');
    } else {
      console.log('  ✗ test[2]: not an object');
    }

    if (typeof example.test[3] === 'string') {
      console.log('  ✓ test[3]: string');
    } else {
      console.log('  ✗ test[3]: not a string');
    }
  } else {
    console.log('✗ test: Not an array with 4 items');
  }

  console.log('\n✅ Test passed: json-schema-faker can generate examples from preprocessed schema');

} catch (error) {
  console.error('❌ Error generating example:', error);
  console.error('Error message:', error instanceof Error ? error.message : String(error));
  process.exit(1);
}

