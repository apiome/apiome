/**
 * Test Scenarios for Auto-Generate Example Button
 *
 * This file demonstrates various test cases for the example generation feature
 */

// Test Case 1: String with Email Format
const emailProperty = {
  baseType: 'string',
  isArray: false,
  data: {
    format: 'email',
    description: 'User email address'
  }
};
// Expected output: "user@example.com"

// Test Case 2: Integer with Constraints
const ageProperty = {
  baseType: 'integer',
  isArray: false,
  data: {
    minimum: '18',
    maximum: '100',
    description: 'User age'
  }
};
// Expected output: 18

// Test Case 3: String with Pattern
const zipCodeProperty = {
  baseType: 'string',
  isArray: false,
  data: {
    pattern: '^\\d{5}$',
    description: 'US ZIP code'
  }
};
// Expected output: "string matching pattern: ^\\d{5}$"

// Test Case 4: Enum Values
const statusProperty = {
  baseType: 'string',
  isArray: false,
  data: {
    enum: ['active', 'inactive', 'pending'],
    description: 'Account status'
  }
};
// Expected output: "active"

// Test Case 5: Object with Nested Properties
const addressProperty = {
  baseType: 'object',
  isArray: false,
  data: {
    description: 'Address object'
  },
  nestedProperties: [
    { name: 'street', data: { type: 'string' } },
    { name: 'city', data: { type: 'string' } },
    { name: 'zipCode', data: { type: 'string' } },
    { name: 'country', data: { type: 'string' } }
  ]
};
// Expected output:
// {
//   "street": "example",
//   "city": "example",
//   "zipCode": "example",
//   "country": "example"
// }

// Test Case 6: Array of Strings
const tagsProperty = {
  baseType: 'string',
  isArray: true,
  data: {
    description: 'Tags array'
  }
};
// Expected output: ["example string"]

// Test Case 7: Array of Numbers
const scoresProperty = {
  baseType: 'number',
  isArray: true,
  data: {
    minimum: '0',
    maximum: '100',
    description: 'Test scores'
  }
};
// Expected output: [0]

// Test Case 8: Date-Time Format
const createdAtProperty = {
  baseType: 'string',
  isArray: false,
  data: {
    format: 'date-time',
    description: 'Creation timestamp'
  }
};
// Expected output: "2025-11-30T12:00:00Z"

// Test Case 9: UUID Format
const idProperty = {
  baseType: 'string',
  isArray: false,
  data: {
    format: 'uuid',
    description: 'Unique identifier'
  }
};
// Expected output: "123e4567-e89b-12d3-a456-426614174000"

// Test Case 10: Boolean Type
const activeProperty = {
  baseType: 'boolean',
  isArray: false,
  data: {
    description: 'Is active'
  }
};
// Expected output: true

// Test Case 11: Number with Exclusive Minimum
const priceProperty = {
  baseType: 'number',
  isArray: false,
  data: {
    minimum: '0',
    exclusiveMinimum: true,
    description: 'Product price'
  }
};
// Expected output: 0.1

// Test Case 12: Reference Type
const personRefProperty = {
  baseType: 'Person',
  isArray: false,
  data: {
    $ref: '#/components/schemas/Person',
    description: 'Person reference'
  }
};
// Expected output:
// {
//   "id": 1,
//   "name": "example Person"
// }

// Test Case 13: Array of Objects with Nested Properties
const contactsProperty = {
  baseType: 'object',
  isArray: true,
  data: {
    description: 'Contact list'
  },
  nestedProperties: [
    { name: 'name', data: { type: 'string' } },
    { name: 'email', data: { type: 'string', format: 'email' } },
    { name: 'phone', data: { type: 'string' } }
  ]
};
// Expected output:
// [
//   {
//     "name": "example",
//     "email": "example",
//     "phone": "example"
//   }
// ]

// Test Case 14: URL Format
const websiteProperty = {
  baseType: 'string',
  isArray: false,
  data: {
    format: 'uri',
    description: 'Website URL'
  }
};
// Expected output: "https://example.com"

// Test Case 15: Number Enum
const priorityProperty = {
  baseType: 'integer',
  isArray: false,
  data: {
    enum: ['1', '2', '3', '4', '5'],
    description: 'Priority level'
  }
};
// Expected output: 1 (parsed as number)

/**
 * Manual Testing Steps:
 *
 * 1. Open the application and navigate to Studio
 * 2. Create or select a project and version
 * 3. Add a class or edit an existing one
 * 4. Add a property or edit an existing property
 * 5. Locate the "Example" field in the property form
 * 6. Click the magic wand icon (✨) in the upper right corner
 * 7. Verify that an appropriate example is generated based on the property type
 * 8. Test with different property types and constraints
 * 9. Verify that the example can be edited manually after generation
 * 10. Verify that clicking the button again regenerates the example
 */

/**
 * Automated Test Ideas:
 *
 * describe('Auto-Generate Example Button', () => {
 *   it('should generate email example for email format', () => {
 *     // Test implementation
 *   });
 *
 *   it('should respect minimum and maximum constraints', () => {
 *     // Test implementation
 *   });
 *
 *   it('should use first enum value when available', () => {
 *     // Test implementation
 *   });
 *
 *   it('should generate nested object with properties', () => {
 *     // Test implementation
 *   });
 *
 *   it('should wrap value in array when isArray is true', () => {
 *     // Test implementation
 *   });
 * });
 */

export const testCases = [
  emailProperty,
  ageProperty,
  zipCodeProperty,
  statusProperty,
  addressProperty,
  tagsProperty,
  scoresProperty,
  createdAtProperty,
  idProperty,
  activeProperty,
  priceProperty,
  personRefProperty,
  contactsProperty,
  websiteProperty,
  priorityProperty,
];

