import { describe, it, expect } from '@jest/globals';
import {
  buildSchemaFromInlineProperties,
  buildStoredInlineSchema,
  validateInlineSchemaCompositions,
} from '../../lib/utils/inline-schema-utils';
import { buildResponseForOpenAPI, type ResponseInfo } from '../../lib/utils/openapi-paths-generator';

describe('buildStoredInlineSchema (import persistence)', () => {
  it('preserves array items and example instead of collapsing to type only', () => {
    const stored = buildStoredInlineSchema({
      type: 'array',
      items: { type: 'string' },
      example: ['EURUSD', 'GBPJPY', 'AUDUSD'],
    });
    expect(stored).toEqual({
      type: 'array',
      items: { type: 'string' },
      example: ['EURUSD', 'GBPJPY', 'AUDUSD'],
    });
  });

  it('preserves scalar constraints (format, enum, example)', () => {
    const stored = buildStoredInlineSchema({
      type: 'string',
      format: 'date-time',
      enum: ['a', 'b'],
      example: 'a',
    });
    expect(stored).toEqual({ type: 'string', format: 'date-time', enum: ['a', 'b'], example: 'a' });
  });

  it('stores an object with properties in the editor property-array node shape', () => {
    const stored = buildStoredInlineSchema({
      type: 'object',
      properties: { id: { type: 'string' }, count: { type: 'integer' } },
    }) as { type: string; properties: Array<{ name: string; data: unknown; parent_id: null }> };
    expect(stored.type).toBe('object');
    expect(stored.properties.map((p) => p.name)).toEqual(['id', 'count']);
    expect(stored.properties[0]).toMatchObject({ name: 'id', data: { type: 'string' }, parent_id: null });
  });

  it('preserves composition keywords (allOf) verbatim', () => {
    const stored = buildStoredInlineSchema({ allOf: [{ $ref: '#/components/schemas/A' }] });
    expect(stored).toEqual({ allOf: [{ $ref: '#/components/schemas/A' }] });
  });
});

describe('inline schema composition', () => {
  it('validateInlineSchemaCompositions flags multiple combinators', () => {
    const errs = validateInlineSchemaCompositions({
      type: 'object',
      properties: [],
      allOf: [{ $ref: '#/components/schemas/A' }],
      oneOf: [{ $ref: '#/components/schemas/B' }],
    });
    expect(errs.some((e) => e.includes('only one of allOf'))).toBe(true);
  });

  it('validateInlineSchemaCompositions flags properties plus composition', () => {
    const errs = validateInlineSchemaCompositions({
      type: 'object',
      properties: [{ id: '1', name: 'x', data: { type: 'string' }, parent_id: null }],
      oneOf: [{ $ref: '#/components/schemas/A' }],
    });
    expect(errs.some((e) => e.includes('cannot be combined'))).toBe(true);
  });

  it('buildSchemaFromInlineProperties emits oneOf-only schema', () => {
    const schema = buildSchemaFromInlineProperties({
      type: 'object',
      properties: [],
      description: 'Errors',
      oneOf: [{ $ref: '#/components/schemas/ErrA' }, { $ref: '#/components/schemas/ErrB' }],
    });
    expect(schema).toEqual({
      description: 'Errors',
      oneOf: [{ $ref: '#/components/schemas/ErrA' }, { $ref: '#/components/schemas/ErrB' }],
    });
  });

  it('buildSchemaFromInlineProperties prefers property tree when properties and composition both set', () => {
    const schema = buildSchemaFromInlineProperties({
      type: 'object',
      properties: [{ id: '1', name: 'id', data: { type: 'string' }, parent_id: null }],
      allOf: [{ $ref: '#/components/schemas/Base' }],
    });
    expect((schema as { type?: string }).type).toBe('object');
    expect((schema as { properties?: unknown }).properties).toHaveProperty('id');
    expect((schema as { allOf?: unknown }).allOf).toBeUndefined();
  });

  it('buildResponseForOpenAPI exports composition for response content type', () => {
    const response: ResponseInfo = {
      id: 'r1',
      status_code: '400',
      description: 'Bad',
      content_types: [
        {
          id: 'ct1',
          media_type: 'application/json',
          inline_schema: {
            type: 'object',
            properties: [],
            oneOf: [
              { $ref: '#/components/schemas/ValidationError' },
              { $ref: '#/components/schemas/ProblemDetails' },
            ],
          },
        },
      ],
    };
    const result = buildResponseForOpenAPI(response);
    const content = result.content as Record<string, { schema: Record<string, unknown> }>;
    expect(content['application/json'].schema).toEqual({
      oneOf: [
        { $ref: '#/components/schemas/ValidationError' },
        { $ref: '#/components/schemas/ProblemDetails' },
      ],
    });
  });
});
