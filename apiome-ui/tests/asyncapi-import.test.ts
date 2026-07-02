/**
 * AsyncAPI Import Test Suite (#236)
 *
 * Tests conversion of AsyncAPI 2.x / 3.x definitions to OpenAPI 3.1–like documents
 * and analysis/import flow support.
 */

import { describe, test, expect } from '@jest/globals';
import {
  convertAsyncAPIToOpenAPI,
  isAsyncAPI,
} from '../src/app/utils/asyncapi-converter';
import { analyzeSpecification, extractFileMetadata } from '../src/app/utils/openapi-analyzer';

const asyncApi20Minimal = {
  asyncapi: '2.0.0',
  info: { title: 'Test API', version: '1.0.0' },
  channels: {},
};

const asyncApi20WithSchemas = {
  asyncapi: '2.0.0',
  info: { title: 'Events API', version: '1.0.0' },
  channels: {
    'user/signedup': {
      subscribe: {
        message: {
          $ref: '#/components/messages/UserSignedUp',
        },
      },
    },
  },
  components: {
    schemas: {
      User: {
        type: 'object',
        properties: {
          id: { type: 'string', format: 'uuid' },
          email: { type: 'string', format: 'email' },
          name: { type: 'string' },
        },
        required: ['id', 'email'],
      },
      UserSignedUp: {
        type: 'object',
        properties: {
          user: { $ref: '#/components/schemas/User' },
          timestamp: { type: 'string', format: 'date-time' },
        },
      },
    },
  },
};

const asyncApi30WithSchemas = {
  asyncapi: '3.0.0',
  info: { title: 'AsyncAPI 3 API', version: '2.0.0' },
  channels: {},
  components: {
    schemas: {
      Order: {
        type: 'object',
        properties: {
          orderId: { type: 'string' },
          total: { type: 'number' },
        },
      },
    },
  },
};

describe('AsyncAPI Import (#236)', () => {
  describe('isAsyncAPI', () => {
    test('returns true for AsyncAPI 2.x document', () => {
      expect(isAsyncAPI(asyncApi20Minimal)).toBe(true);
      expect(isAsyncAPI(asyncApi20WithSchemas)).toBe(true);
    });

    test('returns true for AsyncAPI 3.x document', () => {
      expect(isAsyncAPI(asyncApi30WithSchemas)).toBe(true);
    });

    test('returns false for non-AsyncAPI documents', () => {
      expect(isAsyncAPI({ openapi: '3.1.0' })).toBe(false);
      expect(isAsyncAPI({ swagger: '2.0' })).toBe(false);
      expect(isAsyncAPI(null)).toBe(false);
      expect(isAsyncAPI(undefined)).toBe(false);
      expect(isAsyncAPI({})).toBe(false);
    });
  });

  describe('convertAsyncAPIToOpenAPI', () => {
    test('converts AsyncAPI 2.x to OpenAPI 3.1–like document', () => {
      const result = convertAsyncAPIToOpenAPI(asyncApi20WithSchemas);
      expect(result.success).toBe(true);
      expect(result.document).not.toBeNull();
      expect(result.document.openapi).toBe('3.1.0');
      expect(result.document.info.title).toBe('Events API');
      expect(result.document.info.version).toBe('1.0.0');
      expect(result.document.components.schemas).toEqual(asyncApi20WithSchemas.components.schemas);
    });

    test('converts AsyncAPI 3.x to OpenAPI 3.1–like document', () => {
      const result = convertAsyncAPIToOpenAPI(asyncApi30WithSchemas);
      expect(result.success).toBe(true);
      expect(result.document.openapi).toBe('3.1.0');
      expect(result.document.components.schemas.Order).toEqual(asyncApi30WithSchemas.components.schemas.Order);
    });

    test('preserves $ref paths in schemas', () => {
      const result = convertAsyncAPIToOpenAPI(asyncApi20WithSchemas);
      expect(result.document.components.schemas.UserSignedUp.properties.user.$ref).toBe('#/components/schemas/User');
    });

    test('returns empty schemas when components.schemas is missing', () => {
      const result = convertAsyncAPIToOpenAPI(asyncApi20Minimal);
      expect(result.success).toBe(true);
      expect(Object.keys(result.document.components.schemas)).toHaveLength(0);
      expect(result.warnings.length).toBeGreaterThan(0);
    });

    test('fails for unsupported AsyncAPI version', () => {
      const result = convertAsyncAPIToOpenAPI({ asyncapi: '1.0.0', info: {} });
      expect(result.success).toBe(false);
      expect(result.error).toContain('Unsupported AsyncAPI version');
    });

    test('fails for invalid document', () => {
      expect(convertAsyncAPIToOpenAPI(null).success).toBe(false);
      expect(convertAsyncAPIToOpenAPI({}).success).toBe(false);
    });

    test('adds warning when document has channels and schemas', () => {
      const result = convertAsyncAPIToOpenAPI(asyncApi20WithSchemas);
      expect(result.success).toBe(true);
      const channelWarning = result.warnings.find((w) => w.includes('Channels'));
      expect(channelWarning).toBeDefined();
    });
  });

  describe('analyzeSpecification with AsyncAPI', () => {
    test('accepts AsyncAPI 2.x YAML and converts for import', async () => {
      const yaml = `
asyncapi: 2.0.0
info:
  title: YAML AsyncAPI
  version: 1.0.0
components:
  schemas:
    Event:
      type: object
      properties:
        id: { type: string }
        name: { type: string }
`;
      const result = await analyzeSpecification(yaml, 'spec.yaml');
      expect(result.format).toBe('openapi');
      expect(result.formatSupported).toBe(true);
      expect(result.document).not.toBeNull();
      expect(result.document.openapi).toBe('3.1.0');
      expect(result.document.components.schemas.Event).toBeDefined();
      expect(result.metrics.schemaCount).toBe(1);
    });

    test('accepts AsyncAPI 2.x JSON and converts for import', async () => {
      const content = JSON.stringify(asyncApi20WithSchemas);
      const result = await analyzeSpecification(content, 'spec.json');
      expect(result.formatSupported).toBe(true);
      expect(result.document?.components?.schemas?.User).toBeDefined();
      expect(result.document?.components?.schemas?.UserSignedUp).toBeDefined();
      expect(result.metrics.schemaCount).toBe(2);
    });

    test('accepts AsyncAPI 3.0 and converts for import', async () => {
      const content = JSON.stringify(asyncApi30WithSchemas);
      const result = await analyzeSpecification(content, 'spec.json');
      expect(result.formatSupported).toBe(true);
      expect(result.document?.components?.schemas?.Order).toBeDefined();
      expect(result.metrics.schemaCount).toBe(1);
    });

    test('extractFileMetadata detects AsyncAPI and supported', () => {
      const content = JSON.stringify(asyncApi20WithSchemas);
      const meta = extractFileMetadata(content);
      expect(meta.format).toBe('asyncapi');
      expect(meta.formatSupported).toBe(true);
      expect(meta.formatDisplayName).toContain('AsyncAPI');
    });
  });
});
