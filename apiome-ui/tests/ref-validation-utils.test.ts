/**
 * Tests for ref-validation utility functions
 */

import { describe, it, expect } from '@jest/globals';
import {
  isValidSchemaRef,
  validateSchemaRefs,
  validateOpenAPISchemas,
  extractAllRefs,
  getRefStats,
  formatValidationErrors
} from '../src/app/utils/ref-validation';

describe('ref-validation utilities', () => {
  describe('isValidSchemaRef', () => {
    it('should accept valid OpenAPI schema refs', () => {
      expect(isValidSchemaRef('#/components/schemas/User')).toBe(true);
      expect(isValidSchemaRef('#/components/schemas/Product')).toBe(true);
      expect(isValidSchemaRef('#/components/schemas/OrderItem')).toBe(true);
    });

    it('should accept valid JSON Schema refs', () => {
      expect(isValidSchemaRef('#/$defs/User')).toBe(true);
      expect(isValidSchemaRef('#/$defs/Product')).toBe(true);
    });

    it('should reject refs with property paths', () => {
      expect(isValidSchemaRef('#/components/schemas/User/properties/email')).toBe(false);
      expect(isValidSchemaRef('#/components/schemas/User#/properties/name')).toBe(false);
    });

    it('should reject refs with lowercase schema names', () => {
      expect(isValidSchemaRef('#/components/schemas/user')).toBe(false);
    });

    it('should reject invalid ref formats', () => {
      expect(isValidSchemaRef('User')).toBe(false);
      expect(isValidSchemaRef('')).toBe(false);
      expect(isValidSchemaRef('#/definitions/User')).toBe(false);
    });
  });

  describe('validateSchemaRefs', () => {
    it('should validate schema with correct refs', () => {
      const schema = {
        type: 'object',
        properties: {
          user: { $ref: '#/components/schemas/User' },
          product: { $ref: '#/components/schemas/Product' }
        }
      };

      const result = validateSchemaRefs(schema);
      expect(result.valid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });

    it('should detect invalid property-level refs', () => {
      const schema = {
        type: 'object',
        properties: {
          email: { $ref: '#/components/schemas/User/properties/email' }
        }
      };

      const result = validateSchemaRefs(schema);
      expect(result.valid).toBe(false);
      expect(result.errors).toHaveLength(1);
      expect(result.errors[0].ref).toBe('#/components/schemas/User/properties/email');
    });

    it('should validate nested schemas', () => {
      const schema = {
        type: 'object',
        properties: {
          data: {
            type: 'object',
            properties: {
              user: { $ref: '#/components/schemas/User' }
            }
          }
        }
      };

      const result = validateSchemaRefs(schema);
      expect(result.valid).toBe(true);
    });

    it('should validate allOf/anyOf/oneOf compositions', () => {
      const schema = {
        allOf: [
          { $ref: '#/components/schemas/User' },
          { $ref: '#/components/schemas/Admin' }
        ],
        anyOf: [
          { $ref: '#/components/schemas/Email' },
          { $ref: '#/components/schemas/Phone' }
        ]
      };

      const result = validateSchemaRefs(schema);
      expect(result.valid).toBe(true);
    });

    it('should validate array items refs', () => {
      const schema = {
        type: 'array',
        items: {
          $ref: '#/components/schemas/Product'
        }
      };

      const result = validateSchemaRefs(schema);
      expect(result.valid).toBe(true);
    });

    it('should provide correct error paths', () => {
      const schema = {
        properties: {
          user: {
            properties: {
              contact: {
                $ref: '#/components/schemas/User/properties/email'
              }
            }
          }
        }
      };

      const result = validateSchemaRefs(schema);
      expect(result.errors[0].path).toContain('properties.user.properties.contact');
    });
  });

  describe('validateOpenAPISchemas', () => {
    it('should validate complete OpenAPI document', () => {
      const openApiDoc = {
        openapi: '3.1.0',
        components: {
          schemas: {
            User: {
              type: 'object',
              properties: {
                id: { type: 'string' },
                email: { type: 'string' }
              }
            },
            Order: {
              type: 'object',
              properties: {
                user: { $ref: '#/components/schemas/User' }
              }
            }
          }
        }
      };

      const result = validateOpenAPISchemas(openApiDoc);
      expect(result.valid).toBe(true);
    });

    it('should detect invalid refs in OpenAPI schemas', () => {
      const openApiDoc = {
        components: {
          schemas: {
            Order: {
              properties: {
                userEmail: { $ref: '#/components/schemas/User/properties/email' }
              }
            }
          }
        }
      };

      const result = validateOpenAPISchemas(openApiDoc);
      expect(result.valid).toBe(false);
      expect(result.errors.length).toBeGreaterThan(0);
    });

    it('should handle missing components/schemas gracefully', () => {
      const openApiDoc = { openapi: '3.1.0' };
      const result = validateOpenAPISchemas(openApiDoc);
      expect(result.valid).toBe(true);
    });
  });

  describe('extractAllRefs', () => {
    it('should extract all $ref values', () => {
      const schema = {
        properties: {
          user: { $ref: '#/components/schemas/User' },
          product: { $ref: '#/components/schemas/Product' }
        },
        allOf: [
          { $ref: '#/components/schemas/Base' }
        ]
      };

      const refs = extractAllRefs(schema);
      expect(refs).toHaveLength(3);
      expect(refs).toContain('#/components/schemas/User');
      expect(refs).toContain('#/components/schemas/Product');
      expect(refs).toContain('#/components/schemas/Base');
    });

    it('should extract refs from nested structures', () => {
      const schema = {
        properties: {
          items: {
            type: 'array',
            items: {
              $ref: '#/components/schemas/Item'
            }
          }
        }
      };

      const refs = extractAllRefs(schema);
      expect(refs).toContain('#/components/schemas/Item');
    });

    it('should return empty array for schema without refs', () => {
      const schema = {
        type: 'object',
        properties: {
          name: { type: 'string' }
        }
      };

      const refs = extractAllRefs(schema);
      expect(refs).toHaveLength(0);
    });
  });

  describe('getRefStats', () => {
    it('should calculate ref statistics', () => {
      const schema = {
        properties: {
          user1: { $ref: '#/components/schemas/User' },
          user2: { $ref: '#/components/schemas/User' }, // duplicate
          product: { $ref: '#/components/schemas/Product' }
        }
      };

      const stats = getRefStats(schema);
      expect(stats.total).toBe(3);
      expect(stats.valid).toBe(3);
      expect(stats.invalid).toBe(0);
      expect(stats.uniqueRefs).toBe(2); // User and Product
    });

    it('should count invalid refs', () => {
      const schema = {
        properties: {
          valid: { $ref: '#/components/schemas/User' },
          invalid: { $ref: '#/components/schemas/User/properties/email' }
        }
      };

      const stats = getRefStats(schema);
      expect(stats.total).toBe(2);
      expect(stats.valid).toBe(1);
      expect(stats.invalid).toBe(1);
    });
  });

  describe('formatValidationErrors', () => {
    it('should format validation errors', () => {
      const errors = [
        {
          path: 'properties.user',
          ref: '#/components/schemas/User/properties/email',
          message: 'Invalid ref'
        }
      ];

      const formatted = formatValidationErrors(errors);
      expect(formatted).toContain('Found 1 $ref validation error(s)');
      expect(formatted).toContain('properties.user');
      expect(formatted).toContain('#/components/schemas/User/properties/email');
    });

    it('should handle no errors', () => {
      const formatted = formatValidationErrors([]);
      expect(formatted).toBe('No errors found.');
    });

    it('should format multiple errors', () => {
      const errors = [
        {
          path: 'properties.user',
          ref: '#/components/schemas/User/properties/email',
          message: 'Invalid ref 1'
        },
        {
          path: 'properties.product',
          ref: '#/components/schemas/Product/properties/name',
          message: 'Invalid ref 2'
        }
      ];

      const formatted = formatValidationErrors(errors);
      expect(formatted).toContain('Found 2 $ref validation error(s)');
      expect(formatted).toContain('1. properties.user');
      expect(formatted).toContain('2. properties.product');
    });
  });

  describe('Integration scenarios', () => {
    it('should validate complex real-world schema', () => {
      const schema = {
        type: 'object',
        properties: {
          id: { type: 'string', format: 'uuid' },
          user: { $ref: '#/components/schemas/User' },
          items: {
            type: 'array',
            items: { $ref: '#/components/schemas/OrderItem' }
          },
          shipping: { $ref: '#/components/schemas/Address' },
          billing: { $ref: '#/components/schemas/Address' }
        },
        allOf: [
          { $ref: '#/components/schemas/Timestamped' },
          { $ref: '#/components/schemas/Auditable' }
        ]
      };

      const result = validateSchemaRefs(schema);
      expect(result.valid).toBe(true);

      const stats = getRefStats(schema);
      expect(stats.total).toBe(6);
      expect(stats.uniqueRefs).toBe(5); // User, OrderItem, Address (x2), Timestamped, Auditable
    });

    it('should detect multiple validation issues', () => {
      const schema = {
        properties: {
          email: { $ref: '#/components/schemas/User/properties/email' },
          name: { $ref: '#/components/schemas/User#/properties/name' },
          validRef: { $ref: '#/components/schemas/User' }
        }
      };

      const result = validateSchemaRefs(schema);
      expect(result.valid).toBe(false);
      expect(result.errors).toHaveLength(2);

      const stats = getRefStats(schema);
      expect(stats.invalid).toBe(2);
      expect(stats.valid).toBe(1);
    });
  });
});
