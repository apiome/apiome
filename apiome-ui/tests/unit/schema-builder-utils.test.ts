import { buildArraySchemaFromCurrent } from '../../src/app/ade/studio/paths/components/schema-builder-utils';

describe('buildArraySchemaFromCurrent', () => {
  it('copies $ref schema into array items', () => {
    expect(buildArraySchemaFromCurrent({ $ref: '#/components/schemas/Pet' })).toEqual({
      type: 'array',
      items: { $ref: '#/components/schemas/Pet' },
    });
  });

  it('copies object schema into array items', () => {
    const objectSchema = {
      type: 'object',
      properties: {
        id: { type: 'string' },
      },
    };

    expect(buildArraySchemaFromCurrent(objectSchema)).toEqual({
      type: 'array',
      items: objectSchema,
    });
  });

  it('preserves primitive type as array item type', () => {
    expect(buildArraySchemaFromCurrent({ type: 'integer' })).toEqual({
      type: 'array',
      items: { type: 'integer' },
    });
  });

  it('falls back to string items when current schema is empty', () => {
    expect(buildArraySchemaFromCurrent(null)).toEqual({
      type: 'array',
      items: { type: 'string' },
    });
  });
});
