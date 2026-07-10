import { describe, expect, it } from 'vitest';
import { generateExample, parseMockSeed } from '../synthesis';

describe('parseMockSeed', () => {
  it('accepts integers and stable string hashes', () => {
    expect(parseMockSeed('42')).toBe(42);
    expect(parseMockSeed('alpha')).toBe(parseMockSeed('alpha'));
    expect(parseMockSeed(null)).toBe(0);
  });
});

describe('generateExample', () => {
  it('prefers explicit example metadata', () => {
    expect(generateExample({ type: 'string', example: 'hello' })).toBe('hello');
    expect(generateExample({ const: 42 })).toBe(42);
    expect(generateExample({ type: 'string', default: 'd' })).toBe('d');
    expect(generateExample({ type: 'string', enum: ['a', 'b'] })).toBe('a');
  });

  it('synthesizes bounded integers', () => {
    const schema = { type: 'integer', minimum: 10, maximum: 12 };
    for (let seed = 0; seed < 20; seed++) {
      const value = generateExample(schema, null, { seed });
      expect(value).toBeGreaterThanOrEqual(10);
      expect(value).toBeLessThanOrEqual(12);
    }
  });

  it('synthesizes objects with required properties', () => {
    const schema = {
      type: 'object',
      required: ['id', 'name'],
      properties: {
        id: { type: 'integer' },
        name: { type: 'string' },
        email: { type: 'string', format: 'email' },
      },
    };
    const value = generateExample(schema, null, { seed: 1 }) as Record<string, unknown>;
    expect(value).toMatchObject({
      id: expect.any(Number),
      name: expect.any(String),
      email: expect.stringContaining('@'),
    });
  });

  it('resolves component refs against the spec root', () => {
    const spec = {
      components: {
        schemas: {
          Pet: {
            type: 'object',
            required: ['name'],
            properties: { name: { type: 'string' } },
          },
        },
      },
    };
    const value = generateExample({ $ref: '#/components/schemas/Pet' }, spec, { seed: 2 }) as Record<
      string,
      unknown
    >;
    expect(value.name).toEqual(expect.any(String));
  });

  it('is deterministic for the same seed', () => {
    const schema = {
      type: 'object',
      required: ['id'],
      properties: { id: { type: 'integer' }, label: { type: 'string' } },
    };
    const first = generateExample(schema, null, { seed: 99 });
    const second = generateExample(schema, null, { seed: 99 });
    expect(first).toEqual(second);
  });

  it('changes output when the seed changes', () => {
    const schema = {
      type: 'object',
      properties: { note: { type: 'string' } },
    };
    const first = generateExample(schema, null, { seed: 1 });
    const second = generateExample(schema, null, { seed: 2 });
    expect(first).not.toEqual(second);
  });
});
