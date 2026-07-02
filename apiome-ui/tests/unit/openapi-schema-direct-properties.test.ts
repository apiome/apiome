import { extractDirectProperties } from '../../src/app/utils/openapi-schema-direct-properties';

describe('extractDirectProperties', () => {
  it('merges top-level properties with inline allOf fragments', () => {
    const schema = {
      type: 'object',
      properties: { own: { type: 'string' } },
      required: ['own'],
      allOf: [{ properties: { fromAllOf: { type: 'integer' } }, required: ['fromAllOf'] }],
    };
    const { properties, required } = extractDirectProperties(schema);
    expect(Object.keys(properties).sort()).toEqual(['fromAllOf', 'own']);
    expect(required).toEqual(expect.arrayContaining(['own', 'fromAllOf']));
    expect(required).toHaveLength(2);
  });

  it('returns top-level-only when there is no allOf', () => {
    const schema = {
      type: 'object',
      properties: { id: { type: 'string', format: 'uuid' } },
      required: ['id'],
    };
    const { properties, required } = extractDirectProperties(schema);
    expect(properties).toHaveProperty('id');
    expect(required).toEqual(['id']);
  });

  it('skips $ref and if entries in allOf', () => {
    const schema = {
      allOf: [
        { $ref: '#/components/schemas/Base' },
        { if: {}, then: { properties: { ignored: { type: 'string' } } } },
        { properties: { kept: { type: 'boolean' } } },
      ],
    };
    const { properties } = extractDirectProperties(schema);
    expect(properties).toEqual({ kept: { type: 'boolean' } });
  });

  it('yields empty properties for variant-only anyOf when nothing is collected', () => {
    const schema = {
      anyOf: [{ type: 'string' }, { type: 'number' }],
    };
    const { properties } = extractDirectProperties(schema);
    expect(properties).toEqual({});
  });

  it('keeps top-level properties when anyOf is also present', () => {
    const schema = {
      properties: { tag: { type: 'string' } },
      anyOf: [{ type: 'object', properties: { a: { type: 'string' } } }],
    };
    const { properties } = extractDirectProperties(schema);
    expect(properties).toHaveProperty('tag');
  });
});
