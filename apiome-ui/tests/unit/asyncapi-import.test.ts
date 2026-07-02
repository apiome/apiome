/**
 * Unit tests for #236: Import from AsyncAPI Definition File.
 * Covers asyncapi-converter only: isAsyncAPI and convertAsyncAPIToOpenAPI.
 */

import { describe, it, expect } from '@jest/globals';
import { isAsyncAPI, convertAsyncAPIToOpenAPI } from '../../src/app/utils/asyncapi-converter';

describe('#236 AsyncAPI Import – unit', () => {
  describe('isAsyncAPI', () => {
    it('returns true when doc has string asyncapi field', () => {
      expect(isAsyncAPI({ asyncapi: '2.0.0' })).toBe(true);
      expect(isAsyncAPI({ asyncapi: '2.6.0', info: {} })).toBe(true);
      expect(isAsyncAPI({ asyncapi: '3.0.0' })).toBe(true);
    });

    it('returns false when asyncapi is missing', () => {
      expect(isAsyncAPI({})).toBe(false);
      expect(isAsyncAPI({ openapi: '3.1.0' })).toBe(false);
      expect(isAsyncAPI({ swagger: '2.0' })).toBe(false);
    });

    it('returns false when asyncapi is not a string', () => {
      expect(isAsyncAPI({ asyncapi: 2 })).toBe(false);
      expect(isAsyncAPI({ asyncapi: null })).toBe(false);
      expect(isAsyncAPI({ asyncapi: undefined })).toBe(false);
    });

    it('returns false for null and undefined', () => {
      expect(isAsyncAPI(null)).toBe(false);
      expect(isAsyncAPI(undefined)).toBe(false);
    });

    it('returns false for non-objects', () => {
      expect(isAsyncAPI('asyncapi: 2.0.0')).toBe(false);
      expect(isAsyncAPI(42)).toBe(false);
      expect(isAsyncAPI([])).toBe(false);
    });
  });

  describe('convertAsyncAPIToOpenAPI', () => {
    it('returns failure for null or undefined document', () => {
      const r1 = convertAsyncAPIToOpenAPI(null);
      expect(r1.success).toBe(false);
      expect(r1.document).toBeNull();
      expect(r1.error).toContain('Invalid');

      const r2 = convertAsyncAPIToOpenAPI(undefined);
      expect(r2.success).toBe(false);
    });

    it('returns failure for empty object (not AsyncAPI)', () => {
      const r = convertAsyncAPIToOpenAPI({});
      expect(r.success).toBe(false);
      expect(r.error).toContain('not an AsyncAPI');
    });

    it('returns failure for unsupported AsyncAPI version', () => {
      const r = convertAsyncAPIToOpenAPI({ asyncapi: '1.0.0', info: {} });
      expect(r.success).toBe(false);
      expect(r.error).toMatch(/Unsupported AsyncAPI version.*1\.0\.0/);
    });

    it('returns failure when components.schemas is not an object', () => {
      const r = convertAsyncAPIToOpenAPI({
        asyncapi: '2.0.0',
        info: {},
        components: { schemas: 'invalid' },
      });
      expect(r.success).toBe(false);
      expect(r.error).toContain('Invalid components.schemas');
    });

    it('converts AsyncAPI 2.0 with components.schemas to OpenAPI 3.1 shape', () => {
      const doc = {
        asyncapi: '2.0.0',
        info: { title: 'My API', version: '1.0.0' },
        components: {
          schemas: {
            Payload: { type: 'object', properties: { id: { type: 'string' } } },
          },
        },
      };
      const r = convertAsyncAPIToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document).not.toBeNull();
      expect(r.document.openapi).toBe('3.1.0');
      expect(r.document.info.title).toBe('My API');
      expect(r.document.info.version).toBe('1.0.0');
      expect(r.document.components.schemas.Payload).toEqual(doc.components.schemas.Payload);
    });

    it('converts AsyncAPI 3.0 with components.schemas to OpenAPI 3.1 shape', () => {
      const doc = {
        asyncapi: '3.0.0',
        info: { title: 'Events', version: '2.0.0', description: 'Event API' },
        components: {
          schemas: {
            Event: { type: 'object', properties: { name: { type: 'string' } } },
          },
        },
      };
      const r = convertAsyncAPIToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.openapi).toBe('3.1.0');
      expect(r.document.info.description).toBe('Event API');
      expect(r.document.components.schemas.Event).toEqual(doc.components.schemas.Event);
    });

    it('uses default info when info is missing', () => {
      const doc = { asyncapi: '2.0.0', components: { schemas: {} } };
      const r = convertAsyncAPIToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.info.title).toBe('Imported from AsyncAPI');
      expect(r.document.info.version).toBe('1.0.0');
    });

    it('uses default description for 2.x when info.description is missing', () => {
      const doc = { asyncapi: '2.0.0', info: {}, components: { schemas: {} } };
      const r = convertAsyncAPIToOpenAPI(doc);
      expect(r.document.info.description).toContain('AsyncAPI 2.x');
    });

    it('uses default description for 3.x when info.description is missing', () => {
      const doc = { asyncapi: '3.0.0', info: {}, components: { schemas: {} } };
      const r = convertAsyncAPIToOpenAPI(doc);
      expect(r.document.info.description).toContain('AsyncAPI 3.x');
    });

    it('preserves all schema keys and nested $ref', () => {
      const doc = {
        asyncapi: '2.0.0',
        info: {},
        components: {
          schemas: {
            A: { type: 'object', properties: { b: { $ref: '#/components/schemas/B' } } },
            B: { type: 'object', properties: { id: { type: 'string' } } },
          },
        },
      };
      const r = convertAsyncAPIToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.A.properties.b.$ref).toBe('#/components/schemas/B');
      expect(r.document.components.schemas.B).toEqual(doc.components.schemas.B);
    });

    it('handles schemas with allOf, oneOf, anyOf', () => {
      const doc = {
        asyncapi: '2.0.0',
        info: {},
        components: {
          schemas: {
            Composite: {
              allOf: [
                { $ref: '#/components/schemas/Base' },
                { type: 'object', properties: { extra: { type: 'string' } } },
              ],
            },
            Base: { type: 'object', properties: { id: { type: 'string' } } },
          },
        },
      };
      const r = convertAsyncAPIToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Composite).toEqual(doc.components.schemas.Composite);
    });

    it('uses empty object when components or components.schemas is missing', () => {
      const doc = { asyncapi: '2.0.0', info: {} };
      const r = convertAsyncAPIToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas).toEqual({});
    });

    it('adds warning when no schemas and no channels', () => {
      const doc = { asyncapi: '2.0.0', info: {}, components: { schemas: {} } };
      const r = convertAsyncAPIToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.warnings.some((w) => w.includes('No components.schemas'))).toBe(true);
    });

    it('adds warning when schemas exist and channels exist', () => {
      const doc = {
        asyncapi: '2.0.0',
        info: {},
        channels: { 'user/events': {} },
        components: { schemas: { E: { type: 'object' } } },
      };
      const r = convertAsyncAPIToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.warnings.some((w) => w.includes('Channels') && w.includes('not imported'))).toBe(true);
    });

    it('does not add channels warning when channels is empty', () => {
      const doc = {
        asyncapi: '2.0.0',
        info: {},
        channels: {},
        components: { schemas: { E: { type: 'object' } } },
      };
      const r = convertAsyncAPIToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.warnings.some((w) => w.includes('Channels'))).toBe(false);
    });

    it('accepts optional fileName parameter without affecting result', () => {
      const doc = {
        asyncapi: '2.0.0',
        info: {},
        components: { schemas: { S: { type: 'object' } } },
      };
      const r1 = convertAsyncAPIToOpenAPI(doc);
      const r2 = convertAsyncAPIToOpenAPI(doc, 'my-asyncapi.yaml');
      expect(r1.success).toBe(r2.success);
      expect(r1.document).toEqual(r2.document);
    });

    it('does not mutate the original document', () => {
      const schemas = { Foo: { type: 'object', properties: { x: { type: 'number' } } } };
      const doc = { asyncapi: '2.0.0', info: { title: 'T' }, components: { schemas: { ...schemas } } };
      const before = JSON.stringify(doc);
      convertAsyncAPIToOpenAPI(doc);
      expect(JSON.stringify(doc)).toBe(before);
    });

    it('supports AsyncAPI 2.1 and 2.6 version strings', () => {
      expect(convertAsyncAPIToOpenAPI({ asyncapi: '2.1.0', info: {}, components: { schemas: {} } }).success).toBe(true);
      expect(convertAsyncAPIToOpenAPI({ asyncapi: '2.6.0', info: {}, components: { schemas: {} } }).success).toBe(true);
    });
  });
});
