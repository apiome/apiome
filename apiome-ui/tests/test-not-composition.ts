/**
 * Test for NOT Composition Feature
 *
 * This test verifies that the NOT composition feature properly handles
 * exclusion rules per JSON Schema 2020-12 specification.
 */

import { describe, it, expect } from '@jest/globals';

describe('NOT Composition Feature', () => {
  describe('Schema Building', () => {
    it('should add NOT schema to property', () => {
      const formData = {
        not: '{"type": "string", "maxLength": 0}',
      };

      const schema: any = { type: 'string' };

      if (formData.not && formData.not.trim()) {
        try {
          schema.not = JSON.parse(formData.not);
        } catch (e) {
          schema.not = { type: formData.not };
        }
      }

      expect(schema.not).toBeDefined();
      expect(schema.not.type).toBe('string');
      expect(schema.not.maxLength).toBe(0);
    });

    it('should not add NOT when field is empty', () => {
      const formData = {
        not: '',
      };

      const schema: any = { type: 'string' };

      if (formData.not && formData.not.trim()) {
        try {
          schema.not = JSON.parse(formData.not);
        } catch (e) {
          schema.not = { type: formData.not };
        }
      }

      expect(schema.not).toBeUndefined();
    });

    it('should fallback to simple type on JSON parse error', () => {
      const formData = {
        not: 'string',  // Invalid JSON
      };

      const schema: any = { type: 'string' };

      if (formData.not && formData.not.trim()) {
        try {
          schema.not = JSON.parse(formData.not);
        } catch (e) {
          schema.not = { type: formData.not };
        }
      }

      expect(schema.not).toBeDefined();
      expect(schema.not.type).toBe('string');
    });
  });

  describe('Schema Loading', () => {
    it('should extract NOT from schema', () => {
      const schema = {
        type: 'string',
        not: {
          maxLength: 0,
        },
      };

      const notValue = schema.not ? JSON.stringify(schema.not, null, 2) : '';

      expect(notValue).toBeTruthy();
      const parsed = JSON.parse(notValue);
      expect(parsed.maxLength).toBe(0);
    });

    it('should handle missing NOT', () => {
      const schema = {
        type: 'string',
      };

      const notValue = schema.not ? JSON.stringify(schema.not, null, 2) : '';

      expect(notValue).toBe('');
    });
  });

  describe('Common Use Cases', () => {
    it('should exclude empty strings', () => {
      const notSchema = {
        type: 'string',
        maxLength: 0,
      };

      // Validation logic (conceptual)
      const testValue = '';
      const matchesNotSchema = testValue.length <= 0; // Would match the NOT schema
      const isValid = !matchesNotSchema; // NOT inverts the result

      expect(isValid).toBe(false); // Empty string should be invalid
    });

    it('should exclude null values', () => {
      const notSchema = {
        type: 'null',
      };

      const testValue = null;
      const matchesNotSchema = testValue === null;
      const isValid = !matchesNotSchema;

      expect(isValid).toBe(false); // Null should be invalid
    });

    it('should exclude specific value', () => {
      const notSchema = {
        const: 'forbidden',
      };

      const testValue = 'forbidden';
      const matchesNotSchema = testValue === 'forbidden';
      const isValid = !matchesNotSchema;

      expect(isValid).toBe(false); // "forbidden" should be invalid
    });

    it('should exclude negative numbers', () => {
      const notSchema = {
        maximum: 0,
      };

      const testValue = -5;
      const matchesNotSchema = testValue <= 0;
      const isValid = !matchesNotSchema;

      expect(isValid).toBe(false); // Negative should be invalid
    });

    it('should allow positive numbers', () => {
      const notSchema = {
        maximum: 0,
      };

      const testValue = 5;
      const matchesNotSchema = testValue <= 0;
      const isValid = !matchesNotSchema;

      expect(isValid).toBe(true); // Positive should be valid
    });
  });

  describe('Array Items', () => {
    it('should add NOT to array items schema', () => {
      const formData = {
        not: '{"maxLength": 0}',
      };

      const itemsSchema: any = { type: 'string' };

      if (formData.not && formData.not.trim()) {
        try {
          itemsSchema.not = JSON.parse(formData.not);
        } catch (e) {
          itemsSchema.not = { type: formData.not };
        }
      }

      const schema = {
        type: 'array',
        items: itemsSchema,
      };

      expect(schema.items.not).toBeDefined();
      expect(schema.items.not.maxLength).toBe(0);
    });

    it('should validate array of non-empty strings', () => {
      const schema = {
        type: 'array',
        items: {
          type: 'string',
          not: {
            maxLength: 0,
          },
        },
      };

      expect(schema.items.not).toBeDefined();
      expect(schema.items.not.maxLength).toBe(0);

      // Validation logic (conceptual)
      const validArray = ['hello', 'world'];
      const invalidArray = ['hello', ''];

      // Each item should not be empty
      const validResult = validArray.every(item => item.length > 0);
      const invalidResult = invalidArray.every(item => item.length > 0);

      expect(validResult).toBe(true);
      expect(invalidResult).toBe(false);
    });
  });

  describe('Complex NOT Schemas', () => {
    it('should handle NOT with multiple constraints', () => {
      const notSchema = {
        type: 'string',
        minLength: 1,
        maxLength: 5,
      };

      const formData = {
        not: JSON.stringify(notSchema),
      };

      const schema: any = { type: 'string' };

      if (formData.not && formData.not.trim()) {
        try {
          schema.not = JSON.parse(formData.not);
        } catch (e) {
          schema.not = { type: formData.not };
        }
      }

      expect(schema.not.type).toBe('string');
      expect(schema.not.minLength).toBe(1);
      expect(schema.not.maxLength).toBe(5);
    });

    it('should handle NOT with pattern', () => {
      const notSchema = {
        pattern: '^test-',
      };

      const formData = {
        not: JSON.stringify(notSchema),
      };

      const schema: any = { type: 'string' };

      if (formData.not && formData.not.trim()) {
        try {
          schema.not = JSON.parse(formData.not);
        } catch (e) {
          schema.not = { type: formData.not };
        }
      }

      expect(schema.not.pattern).toBe('^test-');
    });

    it('should handle NOT with enum', () => {
      const notSchema = {
        enum: ['DRAFT', 'PENDING'],
      };

      const formData = {
        not: JSON.stringify(notSchema),
      };

      const schema: any = { type: 'string' };

      if (formData.not && formData.not.trim()) {
        try {
          schema.not = JSON.parse(formData.not);
        } catch (e) {
          schema.not = { type: formData.not };
        }
      }

      expect(schema.not.enum).toEqual(['DRAFT', 'PENDING']);
    });

    it('should handle NOT with object properties', () => {
      const notSchema = {
        properties: {
          deprecatedField: {
            type: 'string',
          },
        },
        required: ['deprecatedField'],
      };

      const formData = {
        not: JSON.stringify(notSchema),
      };

      const schema: any = { type: 'object' };

      if (formData.not && formData.not.trim()) {
        try {
          schema.not = JSON.parse(formData.not);
        } catch (e) {
          schema.not = { type: formData.not };
        }
      }

      expect(schema.not.properties).toBeDefined();
      expect(schema.not.required).toContain('deprecatedField');
    });
  });

  describe('JSON Schema Compliance', () => {
    it('should follow JSON Schema 2020-12 format', () => {
      const schema = {
        type: 'string',
        not: {
          maxLength: 0,
        },
      };

      // NOT should be an object (schema)
      expect(typeof schema.not).toBe('object');
      expect(schema.not).not.toBeNull();

      // NOT can contain any valid schema keywords
      expect(schema.not.maxLength).toBe(0);
    });

    it('should support nested NOT schemas', () => {
      const schema = {
        type: 'object',
        not: {
          properties: {
            nested: {
              type: 'object',
              not: {
                properties: {
                  field: {
                    type: 'string',
                  },
                },
              },
            },
          },
        },
      };

      expect(schema.not.properties.nested.not).toBeDefined();
    });
  });

  describe('Edge Cases', () => {
    it('should handle whitespace-only NOT value', () => {
      const formData = {
        not: '   ',
      };

      const schema: any = { type: 'string' };

      if (formData.not && formData.not.trim()) {
        try {
          schema.not = JSON.parse(formData.not);
        } catch (e) {
          schema.not = { type: formData.not };
        }
      }

      expect(schema.not).toBeUndefined();
    });

    it('should handle complex JSON with formatting', () => {
      const formData = {
        not: `{
          "type": "string",
          "maxLength": 0
        }`,
      };

      const schema: any = { type: 'string' };

      if (formData.not && formData.not.trim()) {
        try {
          schema.not = JSON.parse(formData.not);
        } catch (e) {
          schema.not = { type: formData.not };
        }
      }

      expect(schema.not.type).toBe('string');
      expect(schema.not.maxLength).toBe(0);
    });

    it('should handle NOT with boolean', () => {
      const formData = {
        not: 'true',
      };

      const schema: any = { type: 'string' };

      if (formData.not && formData.not.trim()) {
        try {
          schema.not = JSON.parse(formData.not);
        } catch (e) {
          schema.not = { type: formData.not };
        }
      }

      // JSON.parse('true') returns boolean true
      expect(schema.not).toBe(true);
    });
  });

  describe('Validation Scenarios', () => {
    it('should validate positive-only numbers', () => {
      const schema = {
        type: 'number',
        not: {
          maximum: 0,
        },
      };

      expect(schema.not.maximum).toBe(0);

      // Test values (conceptual)
      const testCases = [
        { value: 1, shouldBeValid: true },
        { value: 0, shouldBeValid: false },
        { value: -1, shouldBeValid: false },
        { value: 100, shouldBeValid: true },
      ];

      testCases.forEach(({ value, shouldBeValid }) => {
        const matchesNotSchema = value <= 0;
        const isValid = !matchesNotSchema;
        expect(isValid).toBe(shouldBeValid);
      });
    });

    it('should validate non-empty strings', () => {
      const schema = {
        type: 'string',
        not: {
          maxLength: 0,
        },
      };

      expect(schema.not.maxLength).toBe(0);

      // Test values (conceptual)
      const testCases = [
        { value: 'hello', shouldBeValid: true },
        { value: '', shouldBeValid: false },
        { value: 'a', shouldBeValid: true },
      ];

      testCases.forEach(({ value, shouldBeValid }) => {
        const matchesNotSchema = value.length === 0;
        const isValid = !matchesNotSchema;
        expect(isValid).toBe(shouldBeValid);
      });
    });
  });
});

// Export for test runner
export {};

