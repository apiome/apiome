/**
 * Unit tests for #591 additive merge and #588/#592 merge strategies.
 * Additive merge: add new properties, keep existing (at every level).
 * Override merge: imported wins; constraints merged for same-name properties.
 */

import { describe, it, expect } from '@jest/globals';
import { mergeClasses, type MergeStrategy } from '../../src/app/utils/schema-merge';
import type { NormalizedClass, NormalizedProperty } from '../../lib/importers';

function prop(
  name: string,
  data: any,
  optsOrChildren?: { description?: string; children?: NormalizedProperty[] } | NormalizedProperty[]
): NormalizedProperty {
  const opts = Array.isArray(optsOrChildren) ? { children: optsOrChildren } : optsOrChildren ?? {};
  return { name, data: data ?? {}, ...opts };
}

function cls(name: string, properties: NormalizedProperty[], opts?: { description?: string }): NormalizedClass {
  return { name, properties, ...opts };
}

describe('schema-merge #591 additive merge', () => {
  describe('mergeClasses additive strategy', () => {
    it('keeps all existing properties and adds new ones from imported', () => {
      const existing = cls('User', [
        prop('id', { type: 'string' }),
        prop('name', { type: 'string' }),
      ]);
      const imported = cls('User', [
        prop('id', { type: 'string' }),
        prop('email', { type: 'string' }),
        prop('createdAt', { type: 'string', format: 'date-time' }),
      ]);

      const merged = mergeClasses(existing, imported, 'additive');

      expect(merged.name).toBe('User');
      expect(merged.properties).toHaveLength(4);
      const names = merged.properties.map((p) => p.name);
      expect(names).toContain('id');
      expect(names).toContain('name');
      expect(names).toContain('email');
      expect(names).toContain('createdAt');
      // Existing properties unchanged (order: existing first, then new)
      expect(merged.properties[0].name).toBe('id');
      expect(merged.properties[1].name).toBe('name');
      expect(merged.properties[2].name).toBe('email');
      expect(merged.properties[3].name).toBe('createdAt');
    });

    it('keeps existing property definition when same name exists in both (no overwrite)', () => {
      const existing = cls('User', [
        prop('id', { type: 'string', minLength: 1 }),
        prop('name', { type: 'string', maxLength: 100 }),
      ]);
      const imported = cls('User', [
        prop('id', { type: 'string', minLength: 5 }),
        prop('name', { type: 'string', maxLength: 50 }),
      ]);

      const merged = mergeClasses(existing, imported, 'additive');

      expect(merged.properties).toHaveLength(2);
      expect(merged.properties[0].data.minLength).toBe(1);
      expect(merged.properties[1].data.maxLength).toBe(100);
    });

    it('keeps existing class name and description', () => {
      const existing = cls('User', [], { description: 'Existing user model' });
      const imported = cls('User', [prop('x', { type: 'string' })], { description: 'Imported user' });

      const merged = mergeClasses(existing, imported, 'additive');

      expect(merged.name).toBe('User');
      expect(merged.description).toBe('Existing user model');
      expect(merged.properties).toHaveLength(1);
    });

    it('recursively merges nested object properties additively', () => {
      const existing = cls('User', [
        prop('address', { type: 'object' }, {
          children: [
            prop('street', { type: 'string' }),
            prop('city', { type: 'string' }),
          ],
        }),
      ]);
      const imported = cls('User', [
        prop('address', { type: 'object' }, {
          children: [
            prop('street', { type: 'string' }),
            prop('country', { type: 'string' }),
          ],
        }),
      ]);

      const merged = mergeClasses(existing, imported, 'additive');

      expect(merged.properties).toHaveLength(1);
      const address = merged.properties[0];
      expect(address.children).toHaveLength(3);
      const childNames = address.children!.map((p) => p.name);
      expect(childNames).toContain('street');
      expect(childNames).toContain('city');
      expect(childNames).toContain('country');
    });

    it('keeps existing nested property when same name in both (no overwrite)', () => {
      const existing = cls('User', [
        prop('meta', { type: 'object' }, {
          children: [prop('version', { type: 'integer', minimum: 0 })],
        }),
      ]);
      const imported = cls('User', [
        prop('meta', { type: 'object' }, {
          children: [prop('version', { type: 'integer', minimum: 10 })],
        }),
      ]);

      const merged = mergeClasses(existing, imported, 'additive');

      const meta = merged.properties[0];
      expect(meta.children).toHaveLength(1);
      expect(meta.children![0].data.minimum).toBe(0);
    });

    it('adds all imported properties when existing has none', () => {
      const existing = cls('User', []);
      const imported = cls('User', [
        prop('id', { type: 'string' }),
        prop('email', { type: 'string' }),
      ]);

      const merged = mergeClasses(existing, imported, 'additive');

      expect(merged.properties).toHaveLength(2);
      expect(merged.properties.map((p) => p.name)).toEqual(['id', 'email']);
    });

    it('keeps all existing when imported has no properties', () => {
      const existing = cls('User', [
        prop('id', { type: 'string' }),
        prop('name', { type: 'string' }),
      ]);
      const imported = cls('User', []);

      const merged = mergeClasses(existing, imported, 'additive');

      expect(merged.properties).toHaveLength(2);
      expect(merged.properties[0].name).toBe('id');
      expect(merged.properties[1].name).toBe('name');
    });

    it('keeps existing schema and description for additive (originalSchemaKey: imported ?? existing)', () => {
      const existing = cls('User', [prop('id', { type: 'string' })], {
        description: 'Existing',
      });
      (existing as any).schema = { type: 'object', title: 'ExistingSchema' };
      (existing as any).originalSchemaKey = 'ExistingUser';
      const imported = cls('User', [prop('email', { type: 'string' })]);
      (imported as any).schema = { type: 'object', title: 'ImportedSchema' };
      (imported as any).originalSchemaKey = 'ImportedUser';

      const merged = mergeClasses(existing, imported, 'additive');

      expect(merged.name).toBe('User');
      expect(merged.description).toBe('Existing');
      expect((merged as any).schema).toEqual({ type: 'object', title: 'ExistingSchema' });
      expect((merged as any).originalSchemaKey).toBe('ImportedUser');
      expect(merged.properties).toHaveLength(2);
    });

    it('does not merge children when only existing has children (additive)', () => {
      const existing = cls('User', [
        prop('address', { type: 'object' }, {
          children: [prop('street', { type: 'string' })],
        }),
      ]);
      const imported = cls('User', [
        prop('address', { type: 'object' }),
      ]);

      const merged = mergeClasses(existing, imported, 'additive');

      expect(merged.properties).toHaveLength(1);
      expect(merged.properties[0].children).toHaveLength(1);
      expect(merged.properties[0].children![0].name).toBe('street');
    });

    it('adds nested property when only imported has children for same name (#594 deep merge)', () => {
      const existing = cls('User', [prop('address', { type: 'object' })]);
      const imported = cls('User', [
        prop('address', { type: 'object' }, {
          children: [prop('country', { type: 'string' })],
        }),
      ]);

      const merged = mergeClasses(existing, imported, 'additive');

      expect(merged.properties).toHaveLength(1);
      expect(merged.properties[0].children).toHaveLength(1);
      expect(merged.properties[0].children![0].name).toBe('country');
      expect(merged.properties[0].children![0].data.type).toBe('string');
    });

    it('additive merge at three levels: adds new at each level', () => {
      const existing = cls('User', [
        prop('root', { type: 'object' }, {
          children: [
            prop('level1', { type: 'object' }, {
              children: [prop('a', { type: 'string' })],
            }),
          ],
        }),
      ]);
      const imported = cls('User', [
        prop('root', { type: 'object' }, {
          children: [
            prop('level1', { type: 'object' }, {
              children: [
                prop('a', { type: 'string' }),
                prop('b', { type: 'string' }),
              ],
            }),
            prop('level1New', { type: 'string' }),
          ],
        }),
      ]);

      const merged = mergeClasses(existing, imported, 'additive');

      const root = merged.properties[0];
      expect(root.children).toHaveLength(2);
      const level1 = root.children!.find((p) => p.name === 'level1');
      expect(level1?.children).toHaveLength(2);
      expect(level1?.children!.map((c) => c.name)).toEqual(expect.arrayContaining(['a', 'b']));
      expect(root.children!.some((p) => p.name === 'level1New')).toBe(true);
    });
  });
});

describe('schema-merge override strategy (#592)', () => {
  it('uses imported for metadata and merges constraints for same-name properties', () => {
    const existing = cls('User', [
      prop('id', { type: 'string', minLength: 1 }),
      prop('name', { type: 'string' }),
    ], { description: 'Existing' });
    const imported = cls('User', [
      prop('id', { type: 'string', minLength: 5 }),
      prop('email', { type: 'string' }),
    ], { description: 'Imported' });

    const merged = mergeClasses(existing, imported, 'override');

    expect(merged.name).toBe('User');
    expect(merged.description).toBe('Imported');
    expect(merged.properties).toHaveLength(3);
    const idProp = merged.properties.find((p) => p.name === 'id');
    expect(idProp?.data.minLength).toBe(5);
    expect(merged.properties.map((p) => p.name)).toEqual(expect.arrayContaining(['id', 'name', 'email']));
  });

  it('keeps existing-only properties after imported ones', () => {
    const existing = cls('User', [
      prop('id', { type: 'string' }),
      prop('legacyField', { type: 'string' }),
    ]);
    const imported = cls('User', [
      prop('id', { type: 'string' }),
      prop('email', { type: 'string' }),
    ]);

    const merged = mergeClasses(existing, imported, 'override');

    expect(merged.properties).toHaveLength(3);
    expect(merged.properties.map((p) => p.name)).toEqual(expect.arrayContaining(['id', 'email', 'legacyField']));
  });

  it('merges numeric constraints to stricter (override)', () => {
    const existing = cls('X', [prop('n', { type: 'integer', minimum: 0, maximum: 100 })]);
    const imported = cls('X', [prop('n', { type: 'integer', minimum: 10, maximum: 90 })]);

    const merged = mergeClasses(existing, imported, 'override');

    const nProp = merged.properties.find((p) => p.name === 'n');
    expect(nProp?.data.minimum).toBe(10);
    expect(nProp?.data.maximum).toBe(90);
  });

  it('merges string length constraints to stricter (override)', () => {
    const existing = cls('X', [prop('s', { type: 'string', minLength: 0, maxLength: 200 })]);
    const imported = cls('X', [prop('s', { type: 'string', minLength: 5, maxLength: 50 })]);

    const merged = mergeClasses(existing, imported, 'override');

    const sProp = merged.properties.find((p) => p.name === 's');
    expect(sProp?.data.minLength).toBe(5);
    expect(sProp?.data.maxLength).toBe(50);
  });

  it('uses imported class schema and originalSchemaKey for override', () => {
    const existing = cls('User', [prop('id', { type: 'string' })]);
    (existing as any).schema = { type: 'object', title: 'Old' };
    (existing as any).originalSchemaKey = 'OldUser';
    const imported = cls('User', [prop('id', { type: 'string' })]);
    (imported as any).schema = { type: 'object', title: 'New' };
    (imported as any).originalSchemaKey = 'NewUser';

    const merged = mergeClasses(existing, imported, 'override');

    expect((merged as any).schema).toEqual({ type: 'object', title: 'New' });
    expect((merged as any).originalSchemaKey).toBe('NewUser');
  });

  it('recursively merges nested properties in override (constraint merge)', () => {
    const existing = cls('User', [
      prop('address', { type: 'object' }, {
        children: [
          prop('street', { type: 'string', maxLength: 200 }),
          prop('city', { type: 'string' }),
        ],
      }),
    ]);
    const imported = cls('User', [
      prop('address', { type: 'object' }, {
        children: [
          prop('street', { type: 'string', maxLength: 100 }),
          prop('country', { type: 'string' }),
        ],
      }),
    ]);

    const merged = mergeClasses(existing, imported, 'override');

    const address = merged.properties.find((p) => p.name === 'address');
    expect(address?.children).toHaveLength(3);
    const street = address?.children!.find((c) => c.name === 'street');
    expect(street?.data.maxLength).toBe(100);
    expect(address?.children!.map((c) => c.name)).toEqual(expect.arrayContaining(['street', 'city', 'country']));
  });
});

describe('schema-merge deep merge (#594)', () => {
  it('recursively merges nested constraint objects (properties, additionalProperties)', () => {
    const existing = cls('X', [
      prop('config', {
        type: 'object',
        properties: {
          a: { type: 'string', minLength: 5 },
          b: { type: 'integer' },
        },
        additionalProperties: { type: 'string', maxLength: 10 },
      }),
    ]);
    const imported = cls('X', [
      prop('config', {
        type: 'object',
        properties: {
          a: { type: 'string', maxLength: 100 },
          c: { type: 'boolean' },
        },
        additionalProperties: { type: 'string', minLength: 1 },
      }),
    ]);

    const merged = mergeClasses(existing, imported, 'override');

    const config = merged.properties.find((p) => p.name === 'config');
    expect(config?.data.properties).toBeDefined();
    expect(config?.data.properties.a).toEqual({ type: 'string', minLength: 5, maxLength: 100 });
    expect(config?.data.properties.b).toEqual({ type: 'integer' });
    expect(config?.data.properties.c).toEqual({ type: 'boolean' });
    expect(config?.data.additionalProperties).toEqual({ type: 'string', maxLength: 10, minLength: 1 });
  });

  it('deep merges patternProperties in constraint objects (override)', () => {
    const existing = cls('X', [
      prop('extra', {
        type: 'object',
        patternProperties: {
          '^x': { type: 'string', maxLength: 50 },
          '^y': { type: 'integer' },
        },
      }),
    ]);
    const imported = cls('X', [
      prop('extra', {
        type: 'object',
        patternProperties: {
          '^x': { type: 'string', minLength: 1 },
          '^z': { type: 'boolean' },
        },
      }),
    ]);

    const merged = mergeClasses(existing, imported, 'override');

    const extra = merged.properties.find((p) => p.name === 'extra');
    expect(extra?.data.patternProperties).toBeDefined();
    expect(extra?.data.patternProperties['^x']).toEqual({ type: 'string', maxLength: 50, minLength: 1 });
    expect(extra?.data.patternProperties['^y']).toEqual({ type: 'integer' });
    expect(extra?.data.patternProperties['^z']).toEqual({ type: 'boolean' });
  });

  it('deep merges items when both are object schemas with nested properties (override)', () => {
    const existing = cls('X', [
      prop('list', {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            id: { type: 'string', minLength: 1 },
            name: { type: 'string' },
          },
        },
      }),
    ]);
    const imported = cls('X', [
      prop('list', {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            id: { type: 'string', maxLength: 100 },
            tag: { type: 'string' },
          },
        },
      }),
    ]);

    const merged = mergeClasses(existing, imported, 'override');

    const list = merged.properties.find((p) => p.name === 'list');
    expect(list?.data.items).toBeDefined();
    expect(list?.data.items.properties).toEqual({
      id: { type: 'string', minLength: 1, maxLength: 100 },
      name: { type: 'string' },
      tag: { type: 'string' },
    });
  });

  it('additive: adds nested children when only imported has children (single level)', () => {
    const existing = cls('User', [prop('profile', { type: 'object' })]);
    const imported = cls('User', [
      prop('profile', { type: 'object' }, {
        children: [
          prop('displayName', { type: 'string' }),
          prop('avatar', { type: 'string', format: 'uri' }),
        ],
      }),
    ]);

    const merged = mergeClasses(existing, imported, 'additive');

    expect(merged.properties).toHaveLength(1);
    const profile = merged.properties[0];
    expect(profile.children).toHaveLength(2);
    expect(profile.children!.map((c) => c.name)).toEqual(expect.arrayContaining(['displayName', 'avatar']));
    expect(profile.children!.find((c) => c.name === 'avatar')?.data.format).toBe('uri');
  });

  it('additive: deep merge when only imported has children at multiple levels', () => {
    const existing = cls('Doc', [
      prop('meta', { type: 'object' }),
    ]);
    const imported = cls('Doc', [
      prop('meta', { type: 'object' }, {
        children: [
          prop('author', { type: 'object' }, {
            children: [
              prop('name', { type: 'string' }),
              prop('email', { type: 'string', format: 'email' }),
            ],
          }),
        ],
      }),
    ]);

    const merged = mergeClasses(existing, imported, 'additive');

    const meta = merged.properties.find((p) => p.name === 'meta');
    expect(meta?.children).toHaveLength(1);
    const author = meta?.children!.find((c) => c.name === 'author');
    expect(author?.children).toHaveLength(2);
    expect(author?.children!.map((c) => c.name)).toEqual(expect.arrayContaining(['name', 'email']));
  });

  it('additive: merges nested when both have children and imported adds more at same level', () => {
    const existing = cls('User', [
      prop('address', { type: 'object' }, {
        children: [prop('city', { type: 'string' })],
      }),
    ]);
    const imported = cls('User', [
      prop('address', { type: 'object' }, {
        children: [
          prop('city', { type: 'string' }),
          prop('postalCode', { type: 'string' }),
        ],
      }),
    ]);

    const merged = mergeClasses(existing, imported, 'additive');

    const address = merged.properties[0];
    expect(address.children).toHaveLength(2);
    expect(address.children!.map((c) => c.name)).toEqual(expect.arrayContaining(['city', 'postalCode']));
  });

  it('override: uses imported nested properties when existing has none', () => {
    const existing = cls('X', [prop('obj', { type: 'object' })]);
    const imported = cls('X', [
      prop('obj', {
        type: 'object',
        properties: {
          k: { type: 'number', minimum: 0 },
        },
      }),
    ]);

    const merged = mergeClasses(existing, imported, 'override');

    const obj = merged.properties.find((p) => p.name === 'obj');
    expect(obj?.data.properties).toEqual({ k: { type: 'number', minimum: 0 } });
  });

  it('override: keeps existing nested properties when imported has none', () => {
    const existing = cls('X', [
      prop('obj', {
        type: 'object',
        properties: { a: { type: 'string' } },
      }),
    ]);
    const imported = cls('X', [prop('obj', { type: 'object' })]);

    const merged = mergeClasses(existing, imported, 'override');

    const obj = merged.properties.find((p) => p.name === 'obj');
    expect(obj?.data.properties).toEqual({ a: { type: 'string' } });
  });

  it('override: merges multiple levels of nested constraint properties', () => {
    const existing = cls('X', [
      prop('root', {
        type: 'object',
        properties: {
          level1: {
            type: 'object',
            properties: {
              a: { type: 'string', minLength: 1 },
              b: { type: 'integer' },
            },
          },
        },
      }),
    ]);
    const imported = cls('X', [
      prop('root', {
        type: 'object',
        properties: {
          level1: {
            type: 'object',
            properties: {
              a: { type: 'string', maxLength: 100 },
              c: { type: 'boolean' },
            },
          },
        },
      }),
    ]);

    const merged = mergeClasses(existing, imported, 'override');

    const root = merged.properties.find((p) => p.name === 'root');
    expect(root?.data.properties?.level1?.properties?.a).toEqual({ type: 'string', minLength: 1, maxLength: 100 });
    expect(root?.data.properties?.level1?.properties?.b).toEqual({ type: 'integer' });
    expect(root?.data.properties?.level1?.properties?.c).toEqual({ type: 'boolean' });
  });
});

describe('schema-merge edge cases', () => {
  it('handles empty properties on both sides (additive)', () => {
    const existing = cls('User', []);
    const imported = cls('User', []);

    const merged = mergeClasses(existing, imported, 'additive');

    expect(merged.name).toBe('User');
    expect(merged.properties).toHaveLength(0);
  });

  it('handles empty properties on both sides (override)', () => {
    const existing = cls('User', []);
    const imported = cls('User', []);

    const merged = mergeClasses(existing, imported, 'override');

    expect(merged.name).toBe('User');
    expect(merged.properties).toHaveLength(0);
  });

  it('additive: no overlap adds both sets in order (existing then imported)', () => {
    const existing = cls('A', [prop('x', { type: 'string' })]);
    const imported = cls('A', [prop('y', { type: 'number' })]);

    const merged = mergeClasses(existing, imported, 'additive');

    expect(merged.properties).toHaveLength(2);
    expect(merged.properties[0].name).toBe('x');
    expect(merged.properties[1].name).toBe('y');
  });

  it('fallback description when existing has none (additive)', () => {
    const existing = cls('User', [], { description: undefined });
    const imported = cls('User', [prop('id', { type: 'string' })], { description: 'Imported desc' });

    const merged = mergeClasses(existing, imported, 'additive');

    expect(merged.description).toBe('Imported desc');
  });

  it('fallback schema when existing has none (additive)', () => {
    const existing = cls('User', []);
    (existing as any).schema = undefined;
    const imported = cls('User', []);
    (imported as any).schema = { type: 'object', additionalProperties: false };

    const merged = mergeClasses(existing, imported, 'additive');

    expect((merged as any).schema).toEqual({ type: 'object', additionalProperties: false });
  });
});

describe('schema-merge selective per-property merge (#593)', () => {
  it('uses per-property override when set: one property override, rest additive', () => {
    const existing = cls('User', [
      prop('id', { type: 'string', maxLength: 50 }),
      prop('name', { type: 'string' }),
    ]);
    const imported = cls('User', [
      prop('id', { type: 'string', maxLength: 100 }),
      prop('email', { type: 'string' }),
    ]);
    const options = {
      schemaKey: 'User',
      propertyMergeStrategies: {
        User: { id: 'override' as const },
      },
    };

    const merged = mergeClasses(existing, imported, 'additive', options);

    expect(merged.properties).toHaveLength(3);
    const idProp = merged.properties.find((p) => p.name === 'id');
    expect(idProp?.data.maxLength).toBe(50);
    const nameProp = merged.properties.find((p) => p.name === 'name');
    expect(nameProp).toBeDefined();
    expect(nameProp?.data).toEqual({ type: 'string' });
    const emailProp = merged.properties.find((p) => p.name === 'email');
    expect(emailProp).toBeDefined();
  });

  it('uses per-property additive when default is override: keep existing for that property', () => {
    const existing = cls('Pet', [
      prop('id', { type: 'integer' }),
      prop('name', { type: 'string', minLength: 1 }),
    ]);
    const imported = cls('Pet', [
      prop('id', { type: 'integer' }),
      prop('name', { type: 'string' }),
    ]);
    const options = {
      schemaKey: 'Pet',
      propertyMergeStrategies: {
        Pet: { name: 'additive' as const },
      },
    };

    const merged = mergeClasses(existing, imported, 'override', options);

    const nameProp = merged.properties.find((p) => p.name === 'name');
    expect(nameProp?.data.minLength).toBe(1);
  });

  it('falls back to default strategy when property not in propertyMergeStrategies', () => {
    const existing = cls('A', [prop('x', { type: 'string' })]);
    const imported = cls('A', [prop('x', { type: 'number' })]);
    const options = {
      schemaKey: 'A',
      propertyMergeStrategies: { A: {} },
    };

    const merged = mergeClasses(existing, imported, 'additive', options);

    expect(merged.properties.find((p) => p.name === 'x')?.data.type).toBe('string');
  });

  it('applies per-property strategy for nested path when provided', () => {
    const existing = cls('User', [
      prop('address', { type: 'object' }, [
        prop('street', { type: 'string', maxLength: 50 }),
        prop('city', { type: 'string' }),
      ]),
    ]);
    const imported = cls('User', [
      prop('address', { type: 'object' }, [
        prop('street', { type: 'string', maxLength: 200 }),
        prop('zip', { type: 'string' }),
      ]),
    ]);
    const options = {
      schemaKey: 'User',
      propertyMergeStrategies: {
        User: { 'address.street': 'override' as const },
      },
    };

    const merged = mergeClasses(existing, imported, 'additive', options);

    const address = merged.properties.find((p) => p.name === 'address');
    expect(address?.children).toBeDefined();
    const street = address?.children!.find((c) => c.name === 'street');
    expect(street?.data.maxLength).toBe(50);
    const city = address?.children!.find((c) => c.name === 'city');
    expect(city).toBeDefined();
    const zip = address?.children!.find((c) => c.name === 'zip');
    expect(zip).toBeDefined();
  });

  it('when options is undefined, behaves like no per-property overrides', () => {
    const existing = cls('X', [prop('a', { type: 'string' })]);
    const imported = cls('X', [prop('a', { type: 'number' })]);

    const mergedWithOptions = mergeClasses(existing, imported, 'additive', undefined);
    const mergedWithoutOptions = mergeClasses(existing, imported, 'additive');

    expect(mergedWithOptions.properties[0].data.type).toBe('string');
    expect(mergedWithoutOptions.properties[0].data.type).toBe('string');
  });

  it('when schemaKey is missing in options, all properties use default strategy', () => {
    const existing = cls('User', [prop('id', { type: 'string' })]);
    const imported = cls('User', [prop('id', { type: 'number' })]);
    const options = {
      schemaKey: undefined,
      propertyMergeStrategies: { User: { id: 'override' as const } },
    };

    const merged = mergeClasses(existing, imported, 'additive', options);

    expect(merged.properties.find((p) => p.name === 'id')?.data.type).toBe('string');
  });

  it('mixed strategies: some additive, some override, preserves property order', () => {
    const existing = cls('Item', [
      prop('a', { type: 'string' }),
      prop('b', { type: 'string' }),
      prop('c', { type: 'string' }),
    ]);
    const imported = cls('Item', [
      prop('a', { type: 'number' }),
      prop('b', { type: 'number' }),
      prop('c', { type: 'number' }),
      prop('d', { type: 'string' }),
    ]);
    const options = {
      schemaKey: 'Item',
      propertyMergeStrategies: {
        Item: {
          a: 'additive' as const,
          b: 'override' as const,
        },
      },
    };

    const merged = mergeClasses(existing, imported, 'additive', options);

    expect(merged.properties.map((p) => p.name)).toEqual(['a', 'b', 'c', 'd']);
    expect(merged.properties.find((p) => p.name === 'a')?.data.type).toBe('string');
    expect(merged.properties.find((p) => p.name === 'b')?.data.type).toBe('number');
    expect(merged.properties.find((p) => p.name === 'c')?.data.type).toBe('string');
    expect(merged.properties.find((p) => p.name === 'd')?.data.type).toBe('string');
  });

  it('per-property override with only existing property (no imported): keeps existing', () => {
    const existing = cls('S', [prop('only', { type: 'string', maxLength: 10 })]);
    const imported = cls('S', []);
    const options = {
      schemaKey: 'S',
      propertyMergeStrategies: { S: { only: 'override' as const } },
    };

    const merged = mergeClasses(existing, imported, 'additive', options);

    expect(merged.properties).toHaveLength(1);
    expect(merged.properties[0].name).toBe('only');
    expect(merged.properties[0].data.maxLength).toBe(10);
  });

  it('per-property additive with only imported property: adds imported', () => {
    const existing = cls('T', []);
    const imported = cls('T', [prop('new', { type: 'integer' })]);
    const options = {
      schemaKey: 'T',
      propertyMergeStrategies: { T: { new: 'additive' as const } },
    };

    const merged = mergeClasses(existing, imported, 'override', options);

    expect(merged.properties).toHaveLength(1);
    expect(merged.properties[0].name).toBe('new');
    expect(merged.properties[0].data.type).toBe('integer');
  });

  it('multiple schemas in propertyMergeStrategies: only matching schemaKey used', () => {
    const existing = cls('Alpha', [prop('x', { type: 'string' })]);
    const imported = cls('Alpha', [prop('x', { type: 'number' })]);
    const options = {
      schemaKey: 'Alpha',
      propertyMergeStrategies: {
        Alpha: { x: 'override' as const },
        Beta: { x: 'additive' as const },
      },
    };

    const merged = mergeClasses(existing, imported, 'additive', options);

    expect(merged.properties.find((p) => p.name === 'x')?.data.type).toBe('number');
  });
});

describe('#595 Array merge strategies (required, enum)', () => {
  it('replace: uses imported required and enum arrays', () => {
    const existing = cls('S', [
      prop('obj', { type: 'object', required: ['a', 'b'], properties: {} }),
      prop('kind', { type: 'string', enum: ['x', 'y'] }),
    ]);
    const imported = cls('S', [
      prop('obj', { type: 'object', required: ['b', 'c'], properties: {} }),
      prop('kind', { type: 'string', enum: ['y', 'z'] }),
    ]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'replace' });

    const obj = merged.properties.find((p) => p.name === 'obj');
    expect(obj?.data.required).toEqual(['b', 'c']);
    const kind = merged.properties.find((p) => p.name === 'kind');
    expect(kind?.data.enum).toEqual(['y', 'z']);
  });

  it('append: existing then imported for required and enum', () => {
    const existing = cls('S', [
      prop('obj', { type: 'object', required: ['a', 'b'], properties: {} }),
      prop('kind', { type: 'string', enum: ['x', 'y'] }),
    ]);
    const imported = cls('S', [
      prop('obj', { type: 'object', required: ['b', 'c'], properties: {} }),
      prop('kind', { type: 'string', enum: ['y', 'z'] }),
    ]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'append' });

    const obj = merged.properties.find((p) => p.name === 'obj');
    expect(obj?.data.required).toEqual(['a', 'b', 'b', 'c']);
    const kind = merged.properties.find((p) => p.name === 'kind');
    expect(kind?.data.enum).toEqual(['x', 'y', 'y', 'z']);
  });

  it('deduplicate: union of required and enum with no duplicates', () => {
    const existing = cls('S', [
      prop('obj', { type: 'object', required: ['a', 'b'], properties: {} }),
      prop('kind', { type: 'string', enum: ['x', 'y'] }),
    ]);
    const imported = cls('S', [
      prop('obj', { type: 'object', required: ['b', 'c'], properties: {} }),
      prop('kind', { type: 'string', enum: ['y', 'z'] }),
    ]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'deduplicate' });

    const obj = merged.properties.find((p) => p.name === 'obj');
    expect(obj?.data.required).toEqual(['a', 'b', 'c']);
    const kind = merged.properties.find((p) => p.name === 'kind');
    expect(kind?.data.enum).toEqual(['x', 'y', 'z']);
  });

  it('default (no option): replace behavior for required', () => {
    const existing = cls('S', [prop('obj', { type: 'object', required: ['a'], properties: {} })]);
    const imported = cls('S', [prop('obj', { type: 'object', required: ['b'], properties: {} })]);

    const merged = mergeClasses(existing, imported, 'override');

    expect(merged.properties[0].data.required).toEqual(['b']);
  });

  it('array merge strategy applies in nested object merge', () => {
    const existing = cls('S', [
      prop('nested', {
        type: 'object',
        properties: {
          inner: { type: 'object', required: ['p', 'q'], properties: {} },
        },
      }),
    ]);
    const imported = cls('S', [
      prop('nested', {
        type: 'object',
        properties: {
          inner: { type: 'object', required: ['q', 'r'], properties: {} },
        },
      }),
    ]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'deduplicate' });

    const inner = merged.properties[0].data.properties?.inner;
    expect(inner?.required).toEqual(['p', 'q', 'r']);
  });

  it('replace with empty imported array: keeps existing array', () => {
    const existing = cls('S', [prop('obj', { type: 'object', required: ['a', 'b'], properties: {} })]);
    const imported = cls('S', [prop('obj', { type: 'object', required: [], properties: {} })]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'replace' });

    expect(merged.properties[0].data.required).toEqual(['a', 'b']);
  });

  it('replace with empty existing array: uses imported array', () => {
    const existing = cls('S', [prop('obj', { type: 'object', required: [], properties: {} })]);
    const imported = cls('S', [prop('obj', { type: 'object', required: ['x', 'y'], properties: {} })]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'replace' });

    expect(merged.properties[0].data.required).toEqual(['x', 'y']);
  });

  it('append with empty existing: result is imported only', () => {
    const existing = cls('S', [prop('kind', { type: 'string', enum: [] })]);
    const imported = cls('S', [prop('kind', { type: 'string', enum: ['a', 'b'] })]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'append' });

    expect(merged.properties[0].data.enum).toEqual(['a', 'b']);
  });

  it('append with empty imported: result is existing only', () => {
    const existing = cls('S', [prop('kind', { type: 'string', enum: ['x', 'y'] })]);
    const imported = cls('S', [prop('kind', { type: 'string', enum: [] })]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'append' });

    expect(merged.properties[0].data.enum).toEqual(['x', 'y']);
  });

  it('deduplicate with enum of numbers', () => {
    const existing = cls('S', [prop('code', { type: 'integer', enum: [1, 2, 3] })]);
    const imported = cls('S', [prop('code', { type: 'integer', enum: [2, 3, 4] })]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'deduplicate' });

    expect(merged.properties[0].data.enum).toEqual([1, 2, 3, 4]);
  });

  it('deduplicate preserves order: existing first then new from imported', () => {
    const existing = cls('S', [prop('tags', { type: 'string', enum: ['b', 'a'] })]);
    const imported = cls('S', [prop('tags', { type: 'string', enum: ['a', 'c'] })]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'deduplicate' });

    expect(merged.properties[0].data.enum).toEqual(['b', 'a', 'c']);
  });

  it('only existing has required: result uses existing (no merge)', () => {
    const existing = cls('S', [prop('obj', { type: 'object', required: ['only'], properties: {} })]);
    const imported = cls('S', [prop('obj', { type: 'object', properties: {} })]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'deduplicate' });

    expect(merged.properties[0].data.required).toEqual(['only']);
  });

  it('only imported has enum: result uses imported (no merge)', () => {
    const existing = cls('S', [prop('status', { type: 'string' })]);
    const imported = cls('S', [prop('status', { type: 'string', enum: ['draft', 'published'] })]);

    const merged = mergeClasses(existing, imported, 'override', { arrayMergeStrategy: 'append' });

    expect(merged.properties[0].data.enum).toEqual(['draft', 'published']);
  });
});
