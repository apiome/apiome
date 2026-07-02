/**
 * Unit tests for duplicate schema detection (#582): schema definition equality
 * and isDuplicateSchema (same name, different definition).
 */
import {
  schemasDefinitionEqual,
  isDuplicateSchema,
} from '../../src/app/utils/schema-definition-equal';

describe('schemasDefinitionEqual', () => {
  test('identical objects are equal', () => {
    const schema = { type: 'object', properties: { name: { type: 'string' } }, required: ['name'] };
    expect(schemasDefinitionEqual(schema, schema)).toBe(true);
  });

  test('same structure, different key order are equal', () => {
    const a = { required: ['name'], type: 'object', properties: { name: { type: 'string' } } };
    const b = { type: 'object', properties: { name: { type: 'string' } }, required: ['name'] };
    expect(schemasDefinitionEqual(a, b)).toBe(true);
  });

  test('different $id or $schema still equal', () => {
    const a = { type: 'object', $id: 'https://a.com/schema', properties: {} };
    const b = { type: 'object', $schema: 'https://json-schema.org/draft/2020-12/schema', properties: {} };
    expect(schemasDefinitionEqual(a, b)).toBe(true);
  });

  test('different type are not equal', () => {
    const a = { type: 'object', properties: {} };
    const b = { type: 'string' };
    expect(schemasDefinitionEqual(a, b)).toBe(false);
  });

  test('different properties are not equal', () => {
    const a = { type: 'object', properties: { name: { type: 'string' } } };
    const b = { type: 'object', properties: { title: { type: 'string' } } };
    expect(schemasDefinitionEqual(a, b)).toBe(false);
  });

  test('nested difference makes not equal', () => {
    const a = { type: 'object', properties: { age: { type: 'integer' } } };
    const b = { type: 'object', properties: { age: { type: 'number' } } };
    expect(schemasDefinitionEqual(a, b)).toBe(false);
  });

  test('x- extension keys are ignored for comparison', () => {
    const a = { type: 'object', properties: {}, 'x-foo': 'bar' };
    const b = { type: 'object', properties: {} };
    expect(schemasDefinitionEqual(a, b)).toBe(true);
  });

  test('null/undefined handling', () => {
    expect(schemasDefinitionEqual(null, null)).toBe(true);
    expect(schemasDefinitionEqual(undefined, undefined)).toBe(true);
    expect(schemasDefinitionEqual(null, { type: 'object' })).toBe(false);
    expect(schemasDefinitionEqual({ type: 'object' }, null)).toBe(false);
  });

  test('empty objects are equal', () => {
    expect(schemasDefinitionEqual({}, {})).toBe(true);
    expect(schemasDefinitionEqual({ type: 'object' }, { type: 'object' })).toBe(true);
  });

  test('arrays: same elements same order are equal', () => {
    const a = { required: ['a', 'b'] };
    const b = { required: ['a', 'b'] };
    expect(schemasDefinitionEqual(a, b)).toBe(true);
  });

  test('arrays: different order are not equal', () => {
    const a = { required: ['a', 'b'] };
    const b = { required: ['b', 'a'] };
    expect(schemasDefinitionEqual(a, b)).toBe(false);
  });

  test('deeply nested objects: equal when structure matches', () => {
    const a = {
      type: 'object',
      properties: {
        address: {
          type: 'object',
          properties: { city: { type: 'string' }, zip: { type: 'string' } },
        },
      },
    };
    const b = {
      type: 'object',
      properties: {
        address: {
          type: 'object',
          properties: { zip: { type: 'string' }, city: { type: 'string' } },
        },
      },
    };
    expect(schemasDefinitionEqual(a, b)).toBe(true);
  });

  test('description difference makes not equal', () => {
    const a = { type: 'string', description: 'First' };
    const b = { type: 'string', description: 'Second' };
    expect(schemasDefinitionEqual(a, b)).toBe(false);
  });

  test('required array difference makes not equal', () => {
    const a = { type: 'object', properties: { a: {}, b: {} }, required: ['a'] };
    const b = { type: 'object', properties: { a: {}, b: {} }, required: ['a', 'b'] };
    expect(schemasDefinitionEqual(a, b)).toBe(false);
  });

  test('multiple x- keys are all ignored', () => {
    const a = { type: 'object', 'x-one': 1, 'x-two': 'y', properties: {} };
    const b = { type: 'object', properties: {} };
    expect(schemasDefinitionEqual(a, b)).toBe(true);
  });
});

describe('isDuplicateSchema (#582)', () => {
  test('returns false when imported name is not in existing list', () => {
    const existingNames = ['User', 'Product'];
    const existingSchemas = { user: { type: 'object', properties: {} }, product: { type: 'object' } };
    expect(isDuplicateSchema('Order', { type: 'object' }, existingNames, existingSchemas)).toBe(false);
    expect(isDuplicateSchema('Order', { type: 'object' }, existingNames)).toBe(false);
  });

  test('name comparison is case-insensitive', () => {
    const existingNames = ['User'];
    const existingSchemas = { user: { type: 'object', properties: { name: { type: 'string' } } } };
    const imported = { type: 'object', properties: { name: { type: 'string' } } };
    expect(isDuplicateSchema('user', imported, existingNames, existingSchemas)).toBe(false);
    expect(isDuplicateSchema('USER', imported, existingNames, existingSchemas)).toBe(false);
  });

  test('returns true when same name and no existingClassSchemas (conservative)', () => {
    const existingNames = ['User'];
    expect(isDuplicateSchema('User', { type: 'object' }, existingNames)).toBe(true);
    expect(isDuplicateSchema('User', { type: 'object' }, existingNames, undefined)).toBe(true);
  });

  test('returns true when same name and existingClassSchemas empty object', () => {
    const existingNames = ['User'];
    expect(isDuplicateSchema('User', { type: 'object' }, existingNames, {})).toBe(true);
  });

  test('returns false when same name and same definition', () => {
    const existingNames = ['User'];
    const schema = { type: 'object', properties: { name: { type: 'string' } }, required: ['name'] };
    const existingSchemas = { user: schema };
    expect(isDuplicateSchema('User', schema, existingNames, existingSchemas)).toBe(false);
    // key order difference still same definition
    expect(
      isDuplicateSchema(
        'User',
        { required: ['name'], type: 'object', properties: { name: { type: 'string' } } },
        existingNames,
        existingSchemas
      )
    ).toBe(false);
  });

  test('returns true when same name and different definition', () => {
    const existingNames = ['User'];
    const existingSchemas = {
      user: { type: 'object', properties: { name: { type: 'string' } } },
    };
    const importedDifferent = { type: 'object', properties: { name: { type: 'string' }, age: { type: 'integer' } } };
    expect(isDuplicateSchema('User', importedDifferent, existingNames, existingSchemas)).toBe(true);
  });

  test('returns true when same name and different type', () => {
    const existingNames = ['Item'];
    const existingSchemas = { item: { type: 'object', properties: {} } };
    expect(isDuplicateSchema('Item', { type: 'string' }, existingNames, existingSchemas)).toBe(true);
  });

  test('empty existingClassNames: never duplicate', () => {
    expect(isDuplicateSchema('User', { type: 'object' }, [], undefined)).toBe(false);
    expect(isDuplicateSchema('User', { type: 'object' }, [], {})).toBe(false);
  });

  test('existing schema with x- only differs in non-x- content', () => {
    const existingNames = ['Foo'];
    const existingSchemas = {
      foo: { type: 'object', properties: { id: { type: 'string' } }, 'x-custom': true },
    };
    const imported = { type: 'object', properties: { id: { type: 'string' } } };
    expect(isDuplicateSchema('Foo', imported, existingNames, existingSchemas)).toBe(false);
  });
});
