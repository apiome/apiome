/**
 * Tests for the resolved-type model (#3476).
 *
 * Covers resolving a property's persisted binding (`$ref` / `primitive_id`,
 * #3475) to its primitive, summarizing the effective JSON Schema (type, format,
 * constraints), coercing free-text examples to the schema's JSON type, and
 * validating those examples against the resolved schema (AJV 2020-12).
 */

import {
  resolvePrimitiveRef,
  summarizeEffectiveSchema,
  coerceExampleValue,
  validateExampleAgainstSchema,
} from '../src/app/components/ade/studio/resolvedTypeModel';
import type { Primitive } from '../src/app/components/ade/studio/PrimitiveSelector';

const makePrimitive = (overrides: Partial<Primitive>): Primitive => ({
  id: 'id-1',
  tenant_id: 'tenant-1',
  name: 'thing',
  description: null,
  category: 'string',
  schema: { type: 'string' },
  tags: [],
  created_by: null,
  is_system: false,
  is_public: false,
  usage_count: 0,
  enabled: true,
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
  namespace: null,
  base_uri: null,
  schema_id: null,
  draft: '2020-12',
  source: 'human',
  refs: [],
  ...overrides,
});

const coreDate = makePrimitive({
  id: 'core-date',
  name: 'date',
  is_system: true,
  namespace: 'std/v0/types',
  schema: { type: 'string', format: 'date' },
});

const tenantSku = makePrimitive({
  id: 'tenant-sku',
  name: 'sku',
  namespace: 'tenant/acme/types',
  schema: { type: 'string', pattern: '^[A-Z0-9-]+$' },
});

describe('resolvePrimitiveRef', () => {
  const all = [coreDate, tenantSku];

  it('resolves by the stored primitive id (FK) first', () => {
    expect(resolvePrimitiveRef('std/v0/types/date', 'tenant-sku', all)).toBe(tenantSku);
  });

  it('falls back to matching the stable $ref when no id matches', () => {
    expect(resolvePrimitiveRef('std/v0/types/date', undefined, all)).toBe(coreDate);
    expect(resolvePrimitiveRef('tenant/acme/types/sku', null, all)).toBe(tenantSku);
  });

  it('returns null when neither id nor ref resolves', () => {
    expect(resolvePrimitiveRef('nope/v0/x', 'missing', all)).toBeNull();
    expect(resolvePrimitiveRef(null, null, all)).toBeNull();
    expect(resolvePrimitiveRef('', '', all)).toBeNull();
  });
});

describe('summarizeEffectiveSchema', () => {
  it('extracts type and format', () => {
    const summary = summarizeEffectiveSchema({ type: 'string', format: 'date' });
    expect(summary.type).toBe('string');
    expect(summary.format).toBe('date');
    expect(summary.constraints).toEqual([]);
  });

  it('collects string constraints in display order', () => {
    const summary = summarizeEffectiveSchema({
      type: 'string',
      pattern: '^[A-Z]+$',
      minLength: 2,
      maxLength: 10,
    });
    expect(summary.constraints).toEqual([
      { label: 'pattern', value: '^[A-Z]+$' },
      { label: 'minLength', value: '2' },
      { label: 'maxLength', value: '10' },
    ]);
  });

  it('collects numeric and array constraints', () => {
    const summary = summarizeEffectiveSchema({
      type: 'integer',
      minimum: 0,
      exclusiveMaximum: 100,
      multipleOf: 5,
    });
    expect(summary.constraints).toContainEqual({ label: 'minimum', value: '0' });
    expect(summary.constraints).toContainEqual({ label: 'exclusiveMaximum', value: '100' });
    expect(summary.constraints).toContainEqual({ label: 'multipleOf', value: '5' });
  });

  it('truncates long enums and renders const', () => {
    const summary = summarizeEffectiveSchema({
      type: 'string',
      enum: ['a', 'b', 'c', 'd', 'e', 'f', 'g'],
    });
    expect(summary.constraints[0]).toEqual({ label: 'enum', value: '[a, b, c, d, e, …]' });

    const constSummary = summarizeEffectiveSchema({ type: 'string', const: 'X' });
    expect(constSummary.constraints).toContainEqual({ label: 'const', value: 'X' });
  });

  it('handles union types and missing type', () => {
    expect(summarizeEffectiveSchema({ type: ['string', 'null'] }).type).toBe('string | null');
    expect(summarizeEffectiveSchema({}).type).toBe('unknown');
  });
});

describe('coerceExampleValue', () => {
  it('keeps strings as-is', () => {
    expect(coerceExampleValue('hello', { type: 'string' })).toBe('hello');
  });

  it('parses numbers and integers', () => {
    expect(coerceExampleValue('42', { type: 'integer' })).toBe(42);
    expect(coerceExampleValue('3.14', { type: 'number' })).toBe(3.14);
  });

  it('throws on non-numeric text for a number', () => {
    expect(() => coerceExampleValue('abc', { type: 'number' })).toThrow(/not a valid number/);
    expect(() => coerceExampleValue('', { type: 'integer' })).toThrow(/not a valid integer/);
  });

  it('parses booleans case-insensitively', () => {
    expect(coerceExampleValue('TRUE', { type: 'boolean' })).toBe(true);
    expect(coerceExampleValue('false', { type: 'boolean' })).toBe(false);
    expect(() => coerceExampleValue('yes', { type: 'boolean' })).toThrow(/not a valid boolean/);
  });

  it('parses arrays and objects as JSON', () => {
    expect(coerceExampleValue('[1, 2]', { type: 'array' })).toEqual([1, 2]);
    expect(coerceExampleValue('{"a": 1}', { type: 'object' })).toEqual({ a: 1 });
    expect(() => coerceExampleValue('[bad', { type: 'array' })).toThrow(/not valid JSON/);
  });
});

describe('validateExampleAgainstSchema', () => {
  it('accepts a valid example against a formatted type', () => {
    const result = validateExampleAgainstSchema('2026-06-23', { type: 'string', format: 'date' });
    expect(result.valid).toBe(true);
    expect(result.coerced).toBe('2026-06-23');
  });

  it('rejects an example that violates the format', () => {
    const result = validateExampleAgainstSchema('not-a-date', { type: 'string', format: 'date' });
    expect(result.valid).toBe(false);
    expect(result.errors && result.errors.length).toBeGreaterThan(0);
  });

  it('rejects a value that violates a constraint', () => {
    const result = validateExampleAgainstSchema('ABCDEFG', { type: 'string', maxLength: 3 });
    expect(result.valid).toBe(false);
  });

  it('validates coerced numbers against numeric constraints', () => {
    expect(validateExampleAgainstSchema('5', { type: 'integer', minimum: 0 }).valid).toBe(true);
    expect(validateExampleAgainstSchema('-1', { type: 'integer', minimum: 0 }).valid).toBe(false);
  });

  it('reports a coercion failure as a single validation error (not a throw)', () => {
    const result = validateExampleAgainstSchema('abc', { type: 'number' });
    expect(result.valid).toBe(false);
    expect(result.errors?.[0].message).toMatch(/not a valid number/);
  });
});
