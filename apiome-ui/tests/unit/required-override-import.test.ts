/**
 * Unit tests for #759: Required field override for imported properties.
 * requiredOverrides: schema key -> { property name -> boolean }.
 * Applied before naming convention; keys use original schema and property names.
 */

import { describe, it, expect } from '@jest/globals';
import { openApiImporter } from '../../lib/importers/openapi';

describe('#759 Required field override for imported properties', () => {
  it('applies required override: make optional property required', () => {
    const document = {
      components: {
        schemas: {
          User: {
            type: 'object',
            properties: {
              id: { type: 'string' },
              name: { type: 'string' },
            },
            required: ['id'],
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['User'],
        requiredOverrides: {
          User: { name: true },
        },
      },
    });
    expect(result.warnings).toBeDefined();
    const cls = result.classes.find((c) => c.originalSchemaKey === 'User' || c.name === 'User');
    expect(cls).toBeDefined();
    const nameProp = cls!.properties?.find((p) => p.name === 'name');
    expect(nameProp?.data.required).toBe(true);
    const idProp = cls!.properties?.find((p) => p.name === 'id');
    expect(idProp?.data.required).toBe(true);
  });

  it('applies required override: make required property optional', () => {
    const document = {
      components: {
        schemas: {
          Item: {
            type: 'object',
            properties: {
              id: { type: 'string' },
              tag: { type: 'string' },
            },
            required: ['id', 'tag'],
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Item'],
        requiredOverrides: {
          Item: { id: false, tag: false },
        },
      },
    });
    const cls = result.classes.find((c) => c.originalSchemaKey === 'Item' || c.name === 'Item');
    expect(cls).toBeDefined();
    expect(cls!.properties?.find((p) => p.name === 'id')?.data.required).toBe(false);
    expect(cls!.properties?.find((p) => p.name === 'tag')?.data.required).toBe(false);
  });

  it('uses original schema key for override (not class name after mapping)', () => {
    const document = {
      components: {
        schemas: {
          UserDto: {
            type: 'object',
            properties: { email: { type: 'string' } },
            required: ['email'],
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['UserDto'],
        classNameMap: { UserDto: 'User' },
        requiredOverrides: {
          UserDto: { email: false },
        },
      },
    });
    const cls = result.classes.find((c) => c.name === 'User');
    expect(cls).toBeDefined();
    expect(cls!.properties?.find((p) => p.name === 'email')?.data.required).toBe(false);
  });

  it('ignores override for non-selected schema', () => {
    const document = {
      components: {
        schemas: {
          A: { type: 'object', properties: { x: { type: 'string' } }, required: ['x'] },
          B: { type: 'object', properties: { y: { type: 'string' } } },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['A'],
        requiredOverrides: {
          B: { y: true },
        },
      },
    });
    expect(result.classes.length).toBe(1);
    expect(result.classes[0].originalSchemaKey).toBe('A');
  });

  it('leaves required unchanged when no override for that property', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              a: { type: 'string' },
              b: { type: 'string' },
              c: { type: 'string' },
            },
            required: ['a', 'c'],
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['S'],
        requiredOverrides: {
          S: { b: true },
        },
      },
    });
    const cls = result.classes[0];
    expect(cls.properties?.find((p) => p.name === 'a')?.data.required).toBe(true);
    expect(cls.properties?.find((p) => p.name === 'b')?.data.required).toBe(true);
    expect(cls.properties?.find((p) => p.name === 'c')?.data.required).toBe(true);
  });

  it('uses spec required when requiredOverrides is omitted', () => {
    const document = {
      components: {
        schemas: {
          Foo: {
            type: 'object',
            properties: { x: { type: 'string' }, y: { type: 'string' } },
            required: ['x'],
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['Foo'] },
    });
    const cls = result.classes[0];
    expect(cls.properties?.find((p) => p.name === 'x')?.data.required).toBe(true);
    expect(cls.properties?.find((p) => p.name === 'y')?.data.required).toBeUndefined();
  });

  it('uses spec required when requiredOverrides is empty object', () => {
    const document = {
      components: {
        schemas: {
          Foo: {
            type: 'object',
            properties: { a: { type: 'string' } },
            required: ['a'],
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Foo'],
        requiredOverrides: {},
      },
    });
    const cls = result.classes[0];
    expect(cls.properties?.find((p) => p.name === 'a')?.data.required).toBe(true);
  });

  it('does not throw when requiredOverrides has unknown schema key', () => {
    const document = {
      components: {
        schemas: {
          Only: {
            type: 'object',
            properties: { v: { type: 'string' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Only'],
        requiredOverrides: {
          NonExistent: { v: true },
        },
      },
    });
    expect(result.classes.length).toBe(1);
    expect(result.classes[0].properties?.find((p) => p.name === 'v')?.data.required).toBeUndefined();
  });

  it('ignores override for unknown property name on schema', () => {
    const document = {
      components: {
        schemas: {
          T: {
            type: 'object',
            properties: { real: { type: 'string' } },
            required: ['real'],
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['T'],
        requiredOverrides: {
          T: { real: false, fakeProp: true },
        },
      },
    });
    const cls = result.classes[0];
    expect(cls.properties?.find((p) => p.name === 'real')?.data.required).toBe(false);
    expect(cls.properties?.some((p) => p.name === 'fakeProp')).toBe(false);
  });

  it('multiple schemas: override only affects specified schema', () => {
    const document = {
      components: {
        schemas: {
          Alpha: {
            type: 'object',
            properties: { a: { type: 'string' } },
            required: ['a'],
          },
          Beta: {
            type: 'object',
            properties: { b: { type: 'string' } },
            required: ['b'],
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Alpha', 'Beta'],
        requiredOverrides: {
          Alpha: { a: false },
        },
      },
    });
    const alpha = result.classes.find((c) => c.originalSchemaKey === 'Alpha');
    const beta = result.classes.find((c) => c.originalSchemaKey === 'Beta');
    expect(alpha!.properties?.find((p) => p.name === 'a')?.data.required).toBe(false);
    expect(beta!.properties?.find((p) => p.name === 'b')?.data.required).toBe(true);
  });

  it('required override is keyed by original property name before naming convention', () => {
    const document = {
      components: {
        schemas: {
          Thing: {
            type: 'object',
            properties: {
              first_name: { type: 'string' },
              last_name: { type: 'string' },
            },
            required: ['first_name'],
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Thing'],
        applyNamingConvention: true,
        propertyNamingConvention: 'camelCase',
        requiredOverrides: {
          Thing: { last_name: true },
        },
      },
    });
    const cls = result.classes[0];
    const firstName = cls.properties?.find((p) => p.name === 'firstName');
    const lastName = cls.properties?.find((p) => p.name === 'lastName');
    expect(firstName?.data.required).toBe(true);
    expect(lastName?.data.required).toBe(true);
  });

  it('works together with type mapping: override then type mapping preserves required', () => {
    const document = {
      components: {
        schemas: {
          Event: {
            type: 'object',
            properties: {
              at: { type: 'string', format: 'date-time' },
              name: { type: 'string' },
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
        requiredOverrides: {
          Event: { name: true, at: false },
        },
        typeMapping: {
          'string:date-time': { type: 'string', format: 'date' },
        },
      },
    });
    const cls = result.classes[0];
    const atProp = cls.properties?.find((p) => p.name === 'at');
    const nameProp = cls.properties?.find((p) => p.name === 'name');
    expect(atProp?.data).toMatchObject({ type: 'string', format: 'date', required: false });
    expect(nameProp?.data.required).toBe(true);
  });

  it('allOf schema: override applies to merged direct properties', () => {
    const document = {
      components: {
        schemas: {
          Extended: {
            type: 'object',
            allOf: [
              { properties: { base: { type: 'string' } }, required: ['base'] },
              { properties: { extra: { type: 'string' } } },
            ],
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Extended'],
        requiredOverrides: {
          Extended: { base: false, extra: true },
        },
      },
    });
    const cls = result.classes[0];
    expect(cls.properties?.find((p) => p.name === 'base')?.data.required).toBe(false);
    expect(cls.properties?.find((p) => p.name === 'extra')?.data.required).toBe(true);
  });
});
