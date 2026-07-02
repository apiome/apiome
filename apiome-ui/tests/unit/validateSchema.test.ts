/**
 * Unit tests for JSON Schema validation used by the database insert modal.
 */

import { validatePayloadAgainstSchema } from '../../lib/database/validateSchema';

describe('validatePayloadAgainstSchema', () => {
  test('returns valid: true when payload matches schema', () => {
    const schema = {
      type: 'object',
      properties: {
        name: { type: 'string' },
        age: { type: 'integer' },
      },
      required: ['name'],
    };
    const payload = { name: 'Alice', age: 30 };
    expect(validatePayloadAgainstSchema(payload, schema)).toEqual({ valid: true });
  });

  test('returns valid: false with errors when required property is missing', () => {
    const schema = {
      type: 'object',
      properties: {
        name: { type: 'string' },
      },
      required: ['name'],
    };
    const payload = {};
    const result = validatePayloadAgainstSchema(payload, schema);
    expect(result.valid).toBe(false);
    expect(result.errors).toBeDefined();
    expect(result.errors!.length).toBeGreaterThan(0);
    expect(result.errors!.some((e) => e.message && e.message.toLowerCase().includes('required'))).toBe(true);
  });

  test('returns valid: false when type does not match', () => {
    const schema = {
      type: 'object',
      properties: {
        count: { type: 'integer' },
      },
    };
    const payload = { count: 'not-a-number' };
    const result = validatePayloadAgainstSchema(payload, schema);
    expect(result.valid).toBe(false);
    expect(result.errors).toBeDefined();
    expect(result.errors!.length).toBeGreaterThan(0);
  });

  test('returns valid: false when value fails pattern', () => {
    const schema = {
      type: 'object',
      properties: {
        id: { type: 'string', pattern: '^[A-Za-z0-9]+$' },
      },
    };
    const payload = { id: 'has-dash!' };
    const result = validatePayloadAgainstSchema(payload, schema);
    expect(result.valid).toBe(false);
    expect(result.errors).toBeDefined();
  });

  test('returns valid: true when string matches pattern', () => {
    const schema = {
      type: 'object',
      properties: {
        id: { type: 'string', pattern: '^[A-Za-z0-9]+$' },
      },
    };
    const payload = { id: 'abc123' };
    expect(validatePayloadAgainstSchema(payload, schema)).toEqual({ valid: true });
  });

  test('returns valid: false with message when schema is invalid', () => {
    const invalidSchema = { type: 'object', properties: { x: { type: 'not-a-type' } } };
    const payload = { x: 1 };
    const result = validatePayloadAgainstSchema(payload, invalidSchema);
    expect(result.valid).toBe(false);
    expect(result.errors).toBeDefined();
    expect(result.errors!.some((e) => e.message && e.message.length > 0)).toBe(true);
  });

  test('handles empty object payload with no required', () => {
    const schema = { type: 'object', properties: { name: { type: 'string' } } };
    expect(validatePayloadAgainstSchema({}, schema)).toEqual({ valid: true });
  });

  test('handles nested object validation', () => {
    const schema = {
      type: 'object',
      properties: {
        address: {
          type: 'object',
          properties: { city: { type: 'string' } },
          required: ['city'],
        },
      },
    };
    expect(validatePayloadAgainstSchema({ address: { city: 'NYC' } }, schema)).toEqual({ valid: true });
    const result = validatePayloadAgainstSchema({ address: {} }, schema);
    expect(result.valid).toBe(false);
    expect(result.errors).toBeDefined();
  });
});
