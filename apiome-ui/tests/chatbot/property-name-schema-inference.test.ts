/**
 * Unit tests for chat refinement property-name → JSON Schema inference (#277, #278).
 */

import {
  inferPropertyShapeFromName,
  inferSchemaShapeFromPropertyName,
} from '../../src/app/ade/studio/components/chatbot/property-name-schema-inference';

describe('inferPropertyShapeFromName', () => {
  it('normalizes case and underscores like created_at → createdAt semantics', () => {
    expect(inferPropertyShapeFromName('created_at').schema).toMatchObject({
      type: 'string',
      format: 'date-time',
    });
  });

  it('suggests string length and format for email', () => {
    expect(inferPropertyShapeFromName('email').schema).toMatchObject({
      type: 'string',
      format: 'email',
      maxLength: 254,
    });
    expect(inferPropertyShapeFromName('email').suggestRequired).toBeUndefined();
  });

  it('suggests numeric ranges for age and percentage', () => {
    expect(inferPropertyShapeFromName('age').schema).toMatchObject({
      type: 'integer',
      minimum: 0,
      maximum: 150,
    });
    expect(inferPropertyShapeFromName('percentage').schema).toMatchObject({
      type: 'number',
      minimum: 0,
      maximum: 100,
    });
  });

  it('suggests pattern validation for slug and ISO codes', () => {
    expect(inferPropertyShapeFromName('slug').schema.pattern).toBe(
      '^[a-z0-9]+(?:-[a-z0-9]+)*$',
    );
    expect(inferPropertyShapeFromName('countryCode').schema).toMatchObject({
      pattern: '^[A-Z]{2}$',
      minLength: 2,
      maxLength: 2,
    });
  });

  it('marks id as uuid-shaped and suggested required', () => {
    const shape = inferPropertyShapeFromName('id');
    expect(shape.schema).toMatchObject({ type: 'string', format: 'uuid' });
    expect(shape.suggestRequired).toBe(true);
  });

  it('returns an empty schema fragment for unknown names', () => {
    expect(inferPropertyShapeFromName('foobar').schema).toEqual({});
  });
});

describe('inferSchemaShapeFromPropertyName', () => {
  it('matches inferPropertyShapeFromName.schema', () => {
    expect(inferSchemaShapeFromPropertyName('price')).toEqual(
      inferPropertyShapeFromName('price').schema,
    );
  });
});
