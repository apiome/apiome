/**
 * Unit tests for #237: Import from RAML definition file.
 * Covers raml-converter (isRAML, convertRAMLToOpenAPI) and parseOpenAPISpec/analyzeSpecification with RAML.
 */

import { describe, it, expect } from '@jest/globals';
import { isRAML, convertRAMLToOpenAPI } from '../../src/app/utils/raml-converter';
import { parseOpenAPISpec } from '../../src/app/utils/openapi-import';
import { analyzeSpecification } from '../../src/app/utils/openapi-analyzer';

const RAML_10_MINIMAL = `#%RAML 1.0
title: Test API
version: v1
baseUri: https://api.example.com
types:
  User:
    type: object
    properties:
      firstname: string
      lastname: string
      age: number
`;

const RAML_10_WITH_REF = `#%RAML 1.0
title: API with Types
types:
  Person:
    type: object
    properties:
      name: string
      title?: string
  Manager:
    type: Person
    properties:
      reports: Person[]
`;

const RAML_10_WITH_ENUM = `#%RAML 1.0
title: Status API
types:
  Status:
    type: string
    enum: [ active, inactive, pending ]
  Entity:
    type: object
    properties:
      id: string
      status: Status
`;

const RAML_10_WITH_DESCRIPTION = `#%RAML 1.0
title: Documented API
version: 1.0
description: A sample API with descriptions
types:
  Person:
    description: A person in the system
    type: object
    properties:
      name: string
      email: string
`;

const RAML_10_OPTIONAL_PROPS = `#%RAML 1.0
title: Optional Props API
types:
  Item:
    type: object
    properties:
      id: string
      code?: string
      tags?: string[]
`;

const RAML_10_PRIMITIVES = `#%RAML 1.0
title: Primitives API
types:
  Mix:
    type: object
    properties:
      flag: boolean
      count: integer
      value: number
      text: string
`;

const RAML_10_EMPTY_TYPES = `#%RAML 1.0
title: Empty Types API
baseUri: https://api.example.com
types: {}
`;

const RAML_10_INLINE_JSON_SCHEMA = `#%RAML 1.0
title: Inline Schema API
types:
  InlineType:
    '{"type":"object","properties":{"x":{"type":"string"}}}'
`;

describe('#237 RAML Import – unit', () => {
  describe('isRAML', () => {
    it('returns true when doc has #%RAML', () => {
      expect(isRAML({ '#%RAML': '1.0' })).toBe(true);
      expect(isRAML({ '#%RAML': '0.8', title: 'API' })).toBe(true);
    });

    it('returns true when doc has title and baseUri (RAML-like root)', () => {
      expect(isRAML({ title: 'My API', baseUri: 'https://api.example.com' })).toBe(true);
      expect(isRAML({ title: 'API', version: '1.0' })).toBe(true);
    });

    it('returns true when doc has title and types only (no baseUri)', () => {
      expect(isRAML({ title: 'API', types: { Foo: { type: 'object' } } })).toBe(true);
    });

    it('returns true when doc has title and schemas only', () => {
      expect(isRAML({ title: 'API', schemas: { Bar: { type: 'object' } } })).toBe(true);
    });

    it('returns false when doc is OpenAPI or Swagger', () => {
      expect(isRAML({ openapi: '3.1.0', title: 'API', version: '1.0' })).toBe(false);
      expect(isRAML({ swagger: '2.0', title: 'API', baseUri: 'http://x.com' })).toBe(false);
      expect(isRAML({ asyncapi: '2.0', title: 'API', baseUri: 'http://x.com' })).toBe(false);
    });

    it('returns false for null and undefined', () => {
      expect(isRAML(null)).toBe(false);
      expect(isRAML(undefined)).toBe(false);
    });

    it('returns false for non-objects', () => {
      expect(isRAML('title: API')).toBe(false);
      expect(isRAML(42)).toBe(false);
      expect(isRAML([])).toBe(false);
    });

    it('returns false when title is missing', () => {
      expect(isRAML({ baseUri: 'https://api.example.com' })).toBe(false);
      expect(isRAML({ types: { A: {} } })).toBe(false);
    });

    it('returns false when title is not a string', () => {
      expect(isRAML({ title: 123, types: {} })).toBe(false);
    });

    it('returns false when types/schemas is not an object', () => {
      expect(isRAML({ title: 'API', types: 'invalid' })).toBe(false);
      expect(isRAML({ title: 'API', schemas: null })).toBe(false);
    });
  });

  describe('convertRAMLToOpenAPI', () => {
    it('returns failure for null or undefined document', () => {
      const r1 = convertRAMLToOpenAPI(null);
      expect(r1.success).toBe(false);
      expect(r1.document).toBeNull();
      expect(r1.error).toContain('Invalid');

      const r2 = convertRAMLToOpenAPI(undefined);
      expect(r2.success).toBe(false);
    });

    it('returns failure for empty object (not RAML)', () => {
      const r = convertRAMLToOpenAPI({});
      expect(r.success).toBe(false);
      expect(r.error).toContain('not a RAML');
    });

    it('converts RAML 1.0 with types to OpenAPI 3.1 shape', () => {
      const doc = {
        '#%RAML': '1.0',
        title: 'My API',
        version: '1.0',
        baseUri: 'https://api.example.com',
        types: {
          User: {
            type: 'object',
            properties: {
              firstname: 'string',
              lastname: 'string',
              age: 'number'
            }
          }
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document).not.toBeNull();
      expect(r.document.openapi).toBe('3.1.0');
      expect(r.document.info.title).toBe('My API');
      expect(r.document.info.version).toBe('1.0');
      expect(r.document.components.schemas.User).toBeDefined();
      expect(r.document.components.schemas.User.type).toBe('object');
      expect(r.document.components.schemas.User.properties.firstname).toEqual({ type: 'string' });
      expect(r.document.components.schemas.User.properties.lastname).toEqual({ type: 'string' });
      expect(r.document.components.schemas.User.properties.age).toEqual({ type: 'number' });
    });

    it('maps baseUri to servers', () => {
      const doc = {
        title: 'API',
        baseUri: 'https://api.example.com/v1',
        types: { X: { type: 'object' } }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.servers).toHaveLength(1);
      expect(r.document.servers[0].url).toBe('https://api.example.com/v1');
    });

    it('substitutes {version} in baseUri with doc.version', () => {
      const doc = {
        title: 'API',
        version: '2.0',
        baseUri: 'https://api.example.com/{version}',
        types: { X: { type: 'object' } }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.servers[0].url).toBe('https://api.example.com/2.0');
    });

    it('uses schemas alias (RAML 0.8) when types is missing', () => {
      const doc = {
        title: 'API',
        schemas: {
          Item: {
            type: 'object',
            properties: { id: 'string' }
          }
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Item).toBeDefined();
      expect(r.document.components.schemas.Item.properties.id).toEqual({ type: 'string' });
    });

    it('converts type reference to $ref', () => {
      const doc = {
        title: 'API',
        types: {
          Person: { type: 'object', properties: { name: 'string' } },
          Manager: {
            type: 'Person',
            properties: { reports: 'Person[]' }
          }
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Person).toBeDefined();
      expect(r.document.components.schemas.Manager).toBeDefined();
      expect(r.document.components.schemas.Manager.allOf).toBeDefined();
      expect(r.document.components.schemas.Manager.allOf[0].$ref).toBe('#/components/schemas/Person');
    });

    it('adds warning when no types or schemas', () => {
      const doc = { title: 'API', baseUri: 'https://api.example.com' };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.warnings.some((w) => w.includes('No types') || w.includes('not extracted'))).toBe(true);
    });

    it('does not mutate the original document', () => {
      const types = { User: { type: 'object', properties: { name: 'string' } } };
      const doc = { title: 'T', types: { ...types } };
      const before = JSON.stringify(doc);
      convertRAMLToOpenAPI(doc);
      expect(JSON.stringify(doc)).toBe(before);
    });

    it('copies info title, version, and description when present', () => {
      const doc = {
        title: 'My Title',
        version: '2.0.0',
        description: 'My description',
        types: { X: { type: 'object' } }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.info.title).toBe('My Title');
      expect(r.document.info.version).toBe('2.0.0');
      expect(r.document.info.description).toBe('My description');
    });

    it('uses default info when title or version missing', () => {
      const doc = { title: 'T', types: { X: { type: 'object' } } };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.info.title).toBe('T');
      expect(r.document.info.version).toBe('1.0.0');
      expect(r.document.info.description).toContain('RAML');
    });

    it('converts enum type to JSON Schema enum', () => {
      const doc = {
        title: 'API',
        types: {
          Status: { type: 'string', enum: ['a', 'b', 'c'] }
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Status).toEqual({
        type: 'string',
        enum: ['a', 'b', 'c']
      });
    });

    it('converts string type with pattern', () => {
      const doc = {
        title: 'API',
        types: {
          Code: { type: 'string', pattern: '^[A-Z0-9]+$' }
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Code.pattern).toBe('^[A-Z0-9]+$');
    });

    it('converts integer and boolean primitives', () => {
      const doc = {
        title: 'API',
        types: {
          Widget: {
            type: 'object',
            properties: {
              count: 'integer',
              active: 'boolean'
            }
          }
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Widget.properties.count).toEqual({ type: 'integer' });
      expect(r.document.components.schemas.Widget.properties.active).toEqual({ type: 'boolean' });
    });

    it('converts optional property (suffix ?) so required array excludes it', () => {
      const doc = {
        title: 'API',
        types: {
          Item: {
            type: 'object',
            properties: {
              id: 'string',
              'code?': 'string'
            }
          }
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Item.properties.id).toBeDefined();
      expect(r.document.components.schemas.Item.properties.code).toBeDefined();
      expect(r.document.components.schemas.Item.required).toEqual(['id']);
    });

    it('converts type that is pure inheritance (no extra properties) to allOf with $ref', () => {
      const doc = {
        title: 'API',
        types: {
          Base: { type: 'object', properties: { id: 'string' } },
          Alias: { type: 'Base' }
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Alias.allOf).toHaveLength(1);
      expect(r.document.components.schemas.Alias.allOf[0].$ref).toBe('#/components/schemas/Base');
    });

    it('parses inline JSON Schema string when type value is valid JSON', () => {
      const doc = {
        title: 'API',
        types: {
          Inline: '{"type":"object","properties":{"name":{"type":"string"}}}'
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Inline).toEqual({
        type: 'object',
        properties: { name: { type: 'string' } }
      });
    });

    it('uses fallback object when type value is non-JSON string', () => {
      const doc = {
        title: 'API',
        types: {
          Bad: 'not json at all'
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Bad.type).toBe('object');
      expect(r.document.components.schemas.Bad.description).toContain('Imported from RAML');
    });

    it('adds warning when inline type string starts with { but is invalid JSON', () => {
      const doc = {
        title: 'API',
        types: {
          Invalid: '{"type": "object"'
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Invalid.type).toBe('object');
      expect(r.warnings.some((w) => w.includes('Invalid') && w.includes('JSON'))).toBe(true);
    });

    it('handles empty types object and adds warning', () => {
      const doc = { title: 'API', baseUri: 'https://api.example.com', types: {} };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(Object.keys(r.document.components.schemas)).toHaveLength(0);
      expect(r.warnings.some((w) => w.includes('No types') || w.includes('not extracted'))).toBe(true);
    });

    it('does not add servers when baseUri is missing', () => {
      const doc = { title: 'API', types: { X: { type: 'object' } } };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.servers).toBeUndefined();
    });

    it('converts type with explicit required array', () => {
      const doc = {
        title: 'API',
        types: {
          User: {
            type: 'object',
            properties: {
              a: 'string',
              b: 'string',
              c: 'string'
            },
            required: ['a', 'c']
          }
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.User.required).toEqual(['a', 'c']);
    });

    it('converts array of primitive to items type', () => {
      const doc = {
        title: 'API',
        types: {
          Tags: {
            type: 'array',
            items: 'string'
          }
        }
      };
      const r = convertRAMLToOpenAPI(doc);
      expect(r.success).toBe(true);
      expect(r.document.components.schemas.Tags).toEqual({
        type: 'array',
        items: { type: 'string' }
      });
    });

    it('accepts optional fileName parameter without affecting result', () => {
      const doc = { title: 'API', types: { S: { type: 'object' } } };
      const r1 = convertRAMLToOpenAPI(doc);
      const r2 = convertRAMLToOpenAPI(doc, 'api.raml');
      expect(r1.success).toBe(r2.success);
      expect(r1.document).toEqual(r2.document);
    });
  });

  describe('parseOpenAPISpec with RAML content', () => {
    it('parses RAML 1.0 YAML string and returns classes', () => {
      const result = parseOpenAPISpec(RAML_10_MINIMAL);
      expect(result.success).toBe(true);
      expect(result.classes).toBeDefined();
      expect(result.classes.length).toBeGreaterThanOrEqual(1);
      const user = result.classes.find((c) => c.name === 'User');
      expect(user).toBeDefined();
      expect(user!.properties.some((p) => p.name === 'firstname')).toBe(true);
      expect(result.warnings.some((w) => w.includes('RAML') && w.includes('OpenAPI'))).toBe(true);
    });

    it('parses RAML with type inheritance and array ref', () => {
      const result = parseOpenAPISpec(RAML_10_WITH_REF);
      expect(result.success).toBe(true);
      expect(result.classes.find((c) => c.name === 'Person')).toBeDefined();
      expect(result.classes.find((c) => c.name === 'Manager')).toBeDefined();
    });

    it('parses RAML with enum type and returns classes', () => {
      const result = parseOpenAPISpec(RAML_10_WITH_ENUM);
      expect(result.success).toBe(true);
      expect(result.classes.find((c) => c.name === 'Status')).toBeDefined();
      expect(result.classes.find((c) => c.name === 'Entity')).toBeDefined();
    });

    it('parses RAML with description and preserves in result', () => {
      const result = parseOpenAPISpec(RAML_10_WITH_DESCRIPTION);
      expect(result.success).toBe(true);
      expect(result.title).toBe('Documented API');
      expect(result.description).toBeDefined();
      const person = result.classes.find((c) => c.name === 'Person');
      expect(person).toBeDefined();
      expect(person!.description).toContain('person');
    });

    it('parses RAML with optional properties and returns correct required', () => {
      const result = parseOpenAPISpec(RAML_10_OPTIONAL_PROPS);
      expect(result.success).toBe(true);
      const item = result.classes.find((c) => c.name === 'Item');
      expect(item).toBeDefined();
      const idProp = item!.properties.find((p) => p.name === 'id');
      const codeProp = item!.properties.find((p) => p.name === 'code');
      expect(idProp?.data.required).toBe(true);
      expect(codeProp?.data.required).toBeFalsy();
    });

    it('parses RAML with multiple primitives (boolean, integer, number)', () => {
      const result = parseOpenAPISpec(RAML_10_PRIMITIVES);
      expect(result.success).toBe(true);
      const mix = result.classes.find((c) => c.name === 'Mix');
      expect(mix).toBeDefined();
      expect(mix!.properties.some((p) => p.name === 'flag')).toBe(true);
      expect(mix!.properties.some((p) => p.name === 'count')).toBe(true);
    });

    it('parses RAML with empty types and returns no importable classes', () => {
      const result = parseOpenAPISpec(RAML_10_EMPTY_TYPES);
      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
      expect(result.classes).toHaveLength(0);
    });

    it('parses RAML with inline JSON Schema type', () => {
      const result = parseOpenAPISpec(RAML_10_INLINE_JSON_SCHEMA);
      expect(result.success).toBe(true);
      const inline = result.classes.find((c) => c.name === 'InlineType');
      expect(inline).toBeDefined();
      expect(inline!.properties.some((p) => p.name === 'x')).toBe(true);
    });

    it('returns conversion warning when parsing RAML', () => {
      const result = parseOpenAPISpec(RAML_10_MINIMAL);
      expect(result.success).toBe(true);
      expect(result.warnings.length).toBeGreaterThanOrEqual(0);
      const ramlWarning = result.warnings.find((w) => w.includes('RAML'));
      expect(ramlWarning).toBeDefined();
    });
  });

  describe('analyzeSpecification with RAML', () => {
    it('analyzes RAML 1.0 and returns OpenAPI-shaped document', async () => {
      const result = await analyzeSpecification(RAML_10_MINIMAL, 'api.raml');
      expect(result.isValid).toBe(true);
      expect(result.format).toBe('openapi');
      expect(result.document).not.toBeNull();
      expect(result.document.openapi).toBe('3.1.0');
      expect(result.document.components.schemas.User).toBeDefined();
      expect(result.formatSupported).toBe(true);
    });

    it('analyzes RAML with multiple types and returns correct schema count', async () => {
      const result = await analyzeSpecification(RAML_10_WITH_REF, 'api.raml');
      expect(result.isValid).toBe(true);
      expect(result.metrics.schemaCount).toBe(2);
      expect(result.document.components.schemas.Person).toBeDefined();
      expect(result.document.components.schemas.Manager).toBeDefined();
    });

    it('analyzes RAML with only title and types (no baseUri)', async () => {
      const result = await analyzeSpecification(RAML_10_WITH_REF, 'spec.raml');
      expect(result.isValid).toBe(true);
      expect(result.format).toBe('openapi');
      expect(result.document.info.title).toBe('API with Types');
    });

    it('analyzes RAML with enum and preserves enum in document', async () => {
      const result = await analyzeSpecification(RAML_10_WITH_ENUM, 'api.raml');
      expect(result.isValid).toBe(true);
      expect(result.document.components.schemas.Status.enum).toEqual(['active', 'inactive', 'pending']);
    });

    it('analyzes RAML with empty types and returns zero schema count', async () => {
      const result = await analyzeSpecification(RAML_10_EMPTY_TYPES, 'api.raml');
      expect(result.isValid).toBe(true);
      expect(result.metrics.schemaCount).toBe(0);
    });
  });
});
