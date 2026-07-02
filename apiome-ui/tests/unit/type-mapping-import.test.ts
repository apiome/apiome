/**
 * Unit tests for #757: Type mapping for imported properties.
 * - External type key format: "type" or "type:format" (e.g. "string:date-time", "integer:int32").
 * - typeMapping in NormalizeOptions maps external keys to internal JSON Schema.
 * - Refs are not modified; array items are recursively mapped.
 */

import { describe, it, expect } from '@jest/globals';
import { openApiImporter, getExternalTypeKey, collectExternalTypeKeysFromDocument } from '../../lib/importers/openapi';

describe('#757 Type mapping for imported properties', () => {
  describe('getExternalTypeKey', () => {
    it('returns type only when format is absent', () => {
      expect(getExternalTypeKey({ type: 'string' })).toBe('string');
      expect(getExternalTypeKey({ type: 'integer' })).toBe('integer');
      expect(getExternalTypeKey({ type: 'boolean' })).toBe('boolean');
    });

    it('returns type:format when format is present', () => {
      expect(getExternalTypeKey({ type: 'string', format: 'date-time' })).toBe('string:date-time');
      expect(getExternalTypeKey({ type: 'integer', format: 'int32' })).toBe('integer:int32');
      expect(getExternalTypeKey({ type: 'number', format: 'double' })).toBe('number:double');
    });

    it('returns null for $ref or missing type', () => {
      expect(getExternalTypeKey({ $ref: '#/components/schemas/Foo' })).toBeNull();
      expect(getExternalTypeKey({})).toBeNull();
      expect(getExternalTypeKey(null)).toBeNull();
    });

    it('handles number and number formats', () => {
      expect(getExternalTypeKey({ type: 'number' })).toBe('number');
      expect(getExternalTypeKey({ type: 'number', format: 'float' })).toBe('number:float');
    });
  });

  describe('collectExternalTypeKeysFromDocument', () => {
    it('collects unique type keys from selected schemas', () => {
      const document = {
        components: {
          schemas: {
            A: {
              type: 'object',
              properties: {
                id: { type: 'integer', format: 'int64' },
                name: { type: 'string' },
                createdAt: { type: 'string', format: 'date-time' },
              },
            },
            B: {
              type: 'object',
              properties: {
                name: { type: 'string' },
                score: { type: 'number', format: 'double' },
              },
            },
          },
        },
      };
      const keys = collectExternalTypeKeysFromDocument(document, ['A', 'B']);
      expect(keys).toEqual(['integer:int64', 'number:double', 'string', 'string:date-time']);
    });

    it('only includes selected schemas', () => {
      const document = {
        components: {
          schemas: {
            A: { type: 'object', properties: { x: { type: 'integer' } } },
            B: { type: 'object', properties: { y: { type: 'string', format: 'uuid' } } },
          },
        },
      };
      const keys = collectExternalTypeKeysFromDocument(document, ['A']);
      expect(keys).toEqual(['integer']);
    });

    it('collects keys from nested object properties', () => {
      const document = {
        components: {
          schemas: {
            Root: {
              type: 'object',
              properties: {
                nested: {
                  type: 'object',
                  properties: {
                    inner: { type: 'string', format: 'date-time' },
                  },
                },
              },
            },
          },
        },
      };
      const keys = collectExternalTypeKeysFromDocument(document, ['Root']);
      // Collects container types (object) and leaf type (string:date-time)
      expect(keys).toContain('string:date-time');
      expect(keys).toContain('object');
      expect(keys.sort()).toEqual(['object', 'string:date-time']);
    });

    it('collects keys from array items', () => {
      const document = {
        components: {
          schemas: {
            List: {
              type: 'object',
              properties: {
                ids: { type: 'array', items: { type: 'integer', format: 'int64' } },
              },
            },
          },
        },
      };
      const keys = collectExternalTypeKeysFromDocument(document, ['List']);
      // Collects array container and item type (integer:int64)
      expect(keys).toContain('integer:int64');
      expect(keys).toContain('array');
      expect(keys.sort()).toEqual(['array', 'integer:int64']);
    });

    it('returns empty array when no schemas selected or document empty', () => {
      const document = { components: { schemas: { X: { type: 'object', properties: { a: { type: 'string' } } } } } };
      expect(collectExternalTypeKeysFromDocument(document, [])).toEqual([]);
      expect(collectExternalTypeKeysFromDocument(null, ['X'])).toEqual([]);
      expect(collectExternalTypeKeysFromDocument({}, ['X'])).toEqual([]);
    });
  });

  describe('normalize with typeMapping', () => {
    it('replaces external type with internal schema for scalar properties', () => {
      const document = {
        components: {
          schemas: {
            Event: {
              type: 'object',
              properties: {
                id: { type: 'integer', format: 'int64' },
                at: { type: 'string', format: 'date-time' },
              },
              required: ['at'],
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['Event'],
          applyNamingConvention: false,
          typeMapping: {
            'integer:int64': { type: 'integer', format: 'int32' },
            'string:date-time': { type: 'string', format: 'date' },
          },
        },
      });
      expect(result.classes).toHaveLength(1);
      const props = result.classes[0].properties!;
      const idProp = props.find((p) => p.name === 'id');
      const atProp = props.find((p) => p.name === 'at');
      expect(idProp?.data).toMatchObject({ type: 'integer', format: 'int32' });
      expect(idProp?.data.required).toBeUndefined();
      expect(atProp?.data).toMatchObject({ type: 'string', format: 'date', required: true });
    });

    it('preserves required when mapping', () => {
      const document = {
        components: {
          schemas: {
            Item: {
              type: 'object',
              properties: {
                name: { type: 'string' },
              },
              required: ['name'],
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['Item'],
          applyNamingConvention: false,
          typeMapping: {
            string: { type: 'string', format: 'uuid' },
          },
        },
      });
      const nameProp = result.classes[0].properties!.find((p) => p.name === 'name');
      expect(nameProp?.data).toEqual({ type: 'string', format: 'uuid', required: true });
    });

    it('does not modify $ref properties', () => {
      const document = {
        components: {
          schemas: {
            Order: {
              type: 'object',
              properties: {
                id: { type: 'integer' },
                customer: { $ref: '#/components/schemas/Customer' },
              },
            },
            Customer: {
              type: 'object',
              properties: { name: { type: 'string' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['Order', 'Customer'],
          applyNamingConvention: false,
          typeMapping: { integer: { type: 'string' } },
        },
      });
      const orderClass = result.classes.find((c) => c.name === 'Order')!;
      const customerProp = orderClass.properties!.find((p) => p.name === 'customer');
      expect(customerProp?.data).toEqual({ $ref: '#/components/schemas/Customer' });
    });

    it('applies mapping to array items', () => {
      const document = {
        components: {
          schemas: {
            Doc: {
              type: 'object',
              properties: {
                timestamps: {
                  type: 'array',
                  items: { type: 'string', format: 'date-time' },
                },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['Doc'],
          applyNamingConvention: false,
          typeMapping: {
            'string:date-time': { type: 'string', format: 'date' },
          },
        },
      });
      const timestampsProp = result.classes[0].properties!.find((p) => p.name === 'timestamps');
      expect(timestampsProp?.data).toEqual({
        type: 'array',
        items: { type: 'string', format: 'date' },
      });
    });

    it('leaves properties unchanged when typeMapping is empty or key not present', () => {
      const document = {
        components: {
          schemas: {
            S: {
              type: 'object',
              properties: {
                a: { type: 'string', format: 'date-time' },
                b: { type: 'integer' },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['S'],
          applyNamingConvention: false,
          typeMapping: {
            'string:date-time': { type: 'string', format: 'date' },
            // integer not mapped
          },
        },
      });
      const aProp = result.classes[0].properties!.find((p) => p.name === 'a');
      const bProp = result.classes[0].properties!.find((p) => p.name === 'b');
      expect(aProp?.data).toEqual({ type: 'string', format: 'date' });
      expect(bProp?.data).toEqual({ type: 'integer' });
    });

    it('applies type mapping to nested inline object children', () => {
      const document = {
        components: {
          schemas: {
            Parent: {
              type: 'object',
              properties: {
                child: {
                  type: 'object',
                  properties: {
                    value: { type: 'number', format: 'double' },
                  },
                },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['Parent'],
          applyNamingConvention: false,
          typeMapping: {
            'number:double': { type: 'number', format: 'float' },
          },
        },
      });
      const childProp = result.classes[0].properties!.find((p) => p.name === 'child');
      expect(childProp?.children).toHaveLength(1);
      const valueProp = childProp?.children!.find((p) => p.name === 'value');
      expect(valueProp?.data).toMatchObject({ type: 'number', format: 'float' });
    });

    it('applies type mapping after naming convention (order of operations)', () => {
      const document = {
        components: {
          schemas: {
            foo_bar: {
              type: 'object',
              properties: {
                created_at: { type: 'string', format: 'date-time' },
              },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['foo_bar'],
          applyNamingConvention: true,
          classNamingConvention: 'PascalCase',
          propertyNamingConvention: 'camelCase',
          typeMapping: { 'string:date-time': { type: 'string', format: 'date' } },
        },
      });
      expect(result.classes[0].name).toBe('FooBar');
      const prop = result.classes[0].properties!.find((p) => p.name === 'createdAt');
      expect(prop).toBeDefined();
      expect(prop?.data).toMatchObject({ type: 'string', format: 'date' });
    });

    it('treats empty selectedSchemas as import all components.schemas (REST default)', () => {
      const document = {
        components: {
          schemas: {
            Alpha: { type: 'object', properties: { x: { type: 'string' } } },
            Beta: { type: 'object', properties: { y: { type: 'integer' } } },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: { selectedSchemas: [], applyNamingConvention: false },
      });
      expect(result.classes.map((c) => c.name).sort()).toEqual(['Alpha', 'Beta']);
    });

    it('produces same classes when typeMapping is undefined or empty', () => {
      const document = {
        components: {
          schemas: {
            S: {
              type: 'object',
              properties: { x: { type: 'integer' } },
            },
          },
        },
      };
      const resultNone = openApiImporter.normalize({
        document,
        options: { selectedSchemas: ['S'], applyNamingConvention: false },
      });
      const resultEmpty = openApiImporter.normalize({
        document,
        options: { selectedSchemas: ['S'], applyNamingConvention: false, typeMapping: {} },
      });
      expect(resultNone.classes[0].properties![0].data).toEqual(resultEmpty.classes[0].properties![0].data);
      expect(resultNone.classes[0].properties![0].data).toEqual({ type: 'integer' });
    });

    it('does not modify array items that are $ref', () => {
      const document = {
        components: {
          schemas: {
            Wrapper: {
              type: 'object',
              properties: {
                items: {
                  type: 'array',
                  items: { $ref: '#/components/schemas/Item' },
                },
              },
            },
            Item: {
              type: 'object',
              properties: { id: { type: 'string' } },
            },
          },
        },
      };
      const result = openApiImporter.normalize({
        document,
        options: {
          selectedSchemas: ['Wrapper', 'Item'],
          applyNamingConvention: false,
          typeMapping: { string: { type: 'integer' } },
        },
      });
      const itemsProp = result.classes.find((c) => c.name === 'Wrapper')!.properties!.find((p) => p.name === 'items');
      expect(itemsProp?.data.items).toEqual({ $ref: '#/components/schemas/Item' });
    });
  });
});
