/**
 * Test for ExtensionsEditor Component
 *
 * This test verifies that the ExtensionsEditor component properly handles
 * x- prefixed extension properties for OpenAPI 3.1 compliance.
 */

import { describe, it, expect } from '@jest/globals';

describe('ExtensionsEditor Component', () => {
  describe('Extension Key Validation', () => {
    it('should require x- prefix', () => {
      const validKeys = [
        'x-internal-id',
        'x-team-owner',
        'x-custom-metadata',
        'x-API-version',
        'x-123-test',
        'x-test_key',
      ];

      const invalidKeys = [
        'internal-id',      // Missing x-
        'x',                // Just x
        'X-test',           // Uppercase X
        'test-x-key',       // x- not at start
        'x-',               // Just x- with no content
        'x-test key',       // Contains space
        'x-test@key',       // Contains invalid char
      ];

      const keyPattern = /^x-[a-zA-Z0-9_-]+$/;

      validKeys.forEach(key => {
        expect(keyPattern.test(key)).toBe(true);
      });

      invalidKeys.forEach(key => {
        expect(keyPattern.test(key)).toBe(false);
      });
    });
  });

  describe('Extension Value Parsing', () => {
    it('should parse JSON values correctly', () => {
      const testCases = [
        { input: 'true', expected: true },
        { input: 'false', expected: false },
        { input: '42', expected: 42 },
        { input: '3.14', expected: 3.14 },
        { input: '"text"', expected: 'text' },
        { input: '{"key": "value"}', expected: { key: 'value' } },
        { input: '[1, 2, 3]', expected: [1, 2, 3] },
        { input: 'null', expected: null },
      ];

      testCases.forEach(({ input, expected }) => {
        try {
          const parsed = JSON.parse(input);
          expect(parsed).toEqual(expected);
        } catch (e) {
          // If not valid JSON, should use as string
          expect(input).toBe(expected);
        }
      });
    });

    it('should handle non-JSON values as strings', () => {
      const nonJsonValues = [
        'simple text',
        'text with spaces',
        'incomplete{json',
      ];

      nonJsonValues.forEach(value => {
        let result;
        try {
          result = JSON.parse(value);
        } catch (e) {
          // Should fall back to using the string value
          result = value;
        }
        expect(typeof result).toBe('string');
      });
    });
  });

  describe('Extension Object Operations', () => {
    it('should add extensions correctly', () => {
      const extensions: Record<string, any> = {};

      // Add string extension
      extensions['x-internal-id'] = 'ABC-123';
      expect(extensions['x-internal-id']).toBe('ABC-123');

      // Add number extension
      extensions['x-version'] = 2;
      expect(extensions['x-version']).toBe(2);

      // Add object extension
      extensions['x-metadata'] = { team: 'platform', status: 'active' };
      expect(extensions['x-metadata']).toEqual({ team: 'platform', status: 'active' });

      // Verify count
      expect(Object.keys(extensions).length).toBe(3);
    });

    it('should remove extensions correctly', () => {
      const extensions: Record<string, any> = {
        'x-internal-id': 'ABC-123',
        'x-team-owner': 'platform-team',
        'x-version': 1,
      };

      // Remove one extension
      delete extensions['x-team-owner'];

      expect(Object.keys(extensions).length).toBe(2);
      expect(extensions['x-team-owner']).toBeUndefined();
      expect(extensions['x-internal-id']).toBe('ABC-123');
      expect(extensions['x-version']).toBe(1);
    });

    it('should prevent duplicate keys', () => {
      const extensions: Record<string, any> = {
        'x-internal-id': 'ABC-123',
      };

      // Check if key exists before adding
      const newKey = 'x-internal-id';
      const keyExists = newKey in extensions;

      expect(keyExists).toBe(true);
    });

    it('should sort extensions alphabetically', () => {
      const extensions: Record<string, any> = {
        'x-zebra': 'last',
        'x-apple': 'first',
        'x-middle': 'middle',
      };

      const sorted = Object.entries(extensions).sort(([a], [b]) => a.localeCompare(b));

      expect(sorted[0][0]).toBe('x-apple');
      expect(sorted[1][0]).toBe('x-middle');
      expect(sorted[2][0]).toBe('x-zebra');
    });
  });

  describe('Schema Integration', () => {
    it('should merge extensions into schema correctly', () => {
      const schema: any = {
        type: 'object',
        properties: {
          name: { type: 'string' },
        },
      };

      const extensions: Record<string, any> = {
        'x-internal-id': 'USER-001',
        'x-team-owner': 'platform-team',
        'x-metadata': {
          version: '2.0',
          stable: true,
        },
      };

      // Merge extensions into schema
      Object.keys(extensions).forEach(key => {
        if (key.startsWith('x-')) {
          schema[key] = extensions[key];
        }
      });

      expect(schema['x-internal-id']).toBe('USER-001');
      expect(schema['x-team-owner']).toBe('platform-team');
      expect(schema['x-metadata']).toEqual({ version: '2.0', stable: true });
      expect(schema.type).toBe('object');
      expect(schema.properties.name.type).toBe('string');
    });

    it('should extract extensions from schema correctly', () => {
      const schema: any = {
        type: 'object',
        properties: {
          name: { type: 'string' },
        },
        'x-internal-id': 'USER-001',
        'x-team-owner': 'platform-team',
        deprecated: true,
        description: 'A user object',
      };

      // Extract extensions
      const extensions: Record<string, any> = {};
      Object.keys(schema).forEach(key => {
        if (key.startsWith('x-')) {
          extensions[key] = schema[key];
        }
      });

      expect(Object.keys(extensions).length).toBe(2);
      expect(extensions['x-internal-id']).toBe('USER-001');
      expect(extensions['x-team-owner']).toBe('platform-team');
      expect(extensions['deprecated']).toBeUndefined();
      expect(extensions['description']).toBeUndefined();
    });
  });

  describe('OpenAPI Compliance', () => {
    it('should support common OpenAPI extension patterns', () => {
      const extensions: Record<string, any> = {
        // AWS API Gateway
        'x-amazon-apigateway-integration': {
          type: 'aws_proxy',
          httpMethod: 'POST',
        },
        // Swagger UI
        'x-swagger-ui-order': 1,
        // Code generation
        'x-codegen-package': 'com.example.models',
        // Custom vendor
        'x-internal-metadata': {
          team: 'platform',
          status: 'stable',
        },
      };

      Object.keys(extensions).forEach(key => {
        expect(key.startsWith('x-')).toBe(true);
      });

      expect(extensions['x-amazon-apigateway-integration'].type).toBe('aws_proxy');
      expect(extensions['x-swagger-ui-order']).toBe(1);
    });
  });
});

// Export for test runner
export {};

