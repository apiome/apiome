/**
 * Unit tests for #760: Property description overrides during import.
 * descriptionOverrides: schema key -> { property name -> description string }.
 * Empty string clears the description. Applied before naming convention.
 */

import { describe, it, expect } from '@jest/globals';
import { openApiImporter } from '../../lib/importers/openapi';

describe('#760 Property description override during import', () => {
  it('applies description override: add description to property without one', () => {
    const document = {
      components: {
        schemas: {
          User: {
            type: 'object',
            properties: {
              id: { type: 'string' },
              name: { type: 'string' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['User'],
        descriptionOverrides: {
          User: { name: 'Full display name of the user' },
        },
      },
    });
    const cls = result.classes.find((c) => c.originalSchemaKey === 'User' || c.name === 'User');
    expect(cls).toBeDefined();
    expect(cls!.properties?.find((p) => p.name === 'name')?.description).toBe('Full display name of the user');
    expect(cls!.properties?.find((p) => p.name === 'id')?.description).toBeUndefined();
  });

  it('applies description override: replace existing description', () => {
    const document = {
      components: {
        schemas: {
          Item: {
            type: 'object',
            properties: {
              id: { type: 'string', description: 'Legacy id field' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Item'],
        descriptionOverrides: {
          Item: { id: 'Unique identifier for the item' },
        },
      },
    });
    const cls = result.classes.find((c) => c.originalSchemaKey === 'Item' || c.name === 'Item');
    expect(cls).toBeDefined();
    expect(cls!.properties?.find((p) => p.name === 'id')?.description).toBe('Unique identifier for the item');
  });

  it('applies description override: empty string clears description', () => {
    const document = {
      components: {
        schemas: {
          Tag: {
            type: 'object',
            properties: {
              name: { type: 'string', description: 'Tag label' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Tag'],
        descriptionOverrides: {
          Tag: { name: '' },
        },
      },
    });
    const cls = result.classes.find((c) => c.originalSchemaKey === 'Tag' || c.name === 'Tag');
    expect(cls).toBeDefined();
    expect(cls!.properties?.find((p) => p.name === 'name')?.description).toBeUndefined();
  });

  it('uses original schema key for override (not class name after mapping)', () => {
    const document = {
      components: {
        schemas: {
          UserDto: {
            type: 'object',
            properties: { email: { type: 'string' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['UserDto'],
        classNameMap: { UserDto: 'User' },
        descriptionOverrides: {
          UserDto: { email: 'User email address' },
        },
      },
    });
    const cls = result.classes.find((c) => c.name === 'User');
    expect(cls).toBeDefined();
    expect(cls!.properties?.find((p) => p.name === 'email')?.description).toBe('User email address');
  });

  it('leaves descriptions unchanged when descriptionOverrides is omitted', () => {
    const document = {
      components: {
        schemas: {
          Pet: {
            type: 'object',
            properties: {
              id: { type: 'integer', description: 'Pet ID' },
              name: { type: 'string' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['Pet'] },
    });
    const cls = result.classes.find((c) => c.originalSchemaKey === 'Pet' || c.name === 'Pet');
    expect(cls).toBeDefined();
    expect(cls!.properties?.find((p) => p.name === 'id')?.description).toBe('Pet ID');
    expect(cls!.properties?.find((p) => p.name === 'name')?.description).toBeUndefined();
  });

  it('ignores unknown schema keys in descriptionOverrides', () => {
    const document = {
      components: {
        schemas: {
          Only: {
            type: 'object',
            properties: { x: { type: 'string' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Only'],
        descriptionOverrides: {
          Other: { x: 'ignored' },
          Only: { x: 'Used' },
        },
      },
    });
    const cls = result.classes.find((c) => c.originalSchemaKey === 'Only' || c.name === 'Only');
    expect(cls).toBeDefined();
    expect(cls!.properties?.find((p) => p.name === 'x')?.description).toBe('Used');
  });

  it('leaves descriptions unchanged when descriptionOverrides is empty object', () => {
    const document = {
      components: {
        schemas: {
          Foo: {
            type: 'object',
            properties: {
              a: { type: 'string', description: 'From spec' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Foo'],
        descriptionOverrides: {},
      },
    });
    const cls = result.classes[0];
    expect(cls.properties?.find((p) => p.name === 'a')?.description).toBe('From spec');
  });

  it('ignores override for unknown property name on schema', () => {
    const document = {
      components: {
        schemas: {
          T: {
            type: 'object',
            properties: { real: { type: 'string', description: 'Real prop' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['T'],
        descriptionOverrides: {
          T: { real: 'Overridden', fakeProp: 'Should not appear' },
        },
      },
    });
    const cls = result.classes[0];
    expect(cls.properties?.find((p) => p.name === 'real')?.description).toBe('Overridden');
    expect(cls.properties?.some((p) => p.name === 'fakeProp')).toBe(false);
  });

  it('multiple schemas: override only affects specified schema', () => {
    const document = {
      components: {
        schemas: {
          Alpha: {
            type: 'object',
            properties: { a: { type: 'string', description: 'Alpha a' } },
          },
          Beta: {
            type: 'object',
            properties: { b: { type: 'string', description: 'Beta b' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Alpha', 'Beta'],
        descriptionOverrides: {
          Alpha: { a: 'Alpha description overridden' },
        },
      },
    });
    const alpha = result.classes.find((c) => c.originalSchemaKey === 'Alpha');
    const beta = result.classes.find((c) => c.originalSchemaKey === 'Beta');
    expect(alpha!.properties?.find((p) => p.name === 'a')?.description).toBe('Alpha description overridden');
    expect(beta!.properties?.find((p) => p.name === 'b')?.description).toBe('Beta b');
  });

  it('description override is keyed by original property name before naming convention', () => {
    const document = {
      components: {
        schemas: {
          Thing: {
            type: 'object',
            properties: {
              first_name: { type: 'string' },
              last_name: { type: 'string' },
            },
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
        descriptionOverrides: {
          Thing: { first_name: 'First name', last_name: 'Last name' },
        },
      },
    });
    const cls = result.classes[0];
    const firstName = cls.properties?.find((p) => p.name === 'firstName');
    const lastName = cls.properties?.find((p) => p.name === 'lastName');
    expect(firstName?.description).toBe('First name');
    expect(lastName?.description).toBe('Last name');
  });

  it('works together with required override and type mapping', () => {
    const document = {
      components: {
        schemas: {
          Event: {
            type: 'object',
            properties: {
              at: { type: 'string', format: 'date-time', description: 'When' },
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
        descriptionOverrides: {
          Event: { at: 'Event timestamp', name: 'Event name' },
        },
        requiredOverrides: {
          Event: { name: true },
        },
        typeMapping: {
          'string:date-time': { type: 'string', format: 'date' },
        },
      },
    });
    const cls = result.classes[0];
    const atProp = cls.properties?.find((p) => p.name === 'at');
    const nameProp = cls.properties?.find((p) => p.name === 'name');
    expect(atProp?.description).toBe('Event timestamp');
    expect(atProp?.data).toMatchObject({ type: 'string', format: 'date' });
    expect(nameProp?.description).toBe('Event name');
    expect(nameProp?.data.required).toBe(true);
  });

  it('allOf schema: description override applies to merged direct properties', () => {
    const document = {
      components: {
        schemas: {
          Extended: {
            type: 'object',
            allOf: [
              { properties: { base: { type: 'string', description: 'Base field' } } },
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
        descriptionOverrides: {
          Extended: { base: 'Overridden base', extra: 'Extra field description' },
        },
      },
    });
    const cls = result.classes[0];
    expect(cls.properties?.find((p) => p.name === 'base')?.description).toBe('Overridden base');
    expect(cls.properties?.find((p) => p.name === 'extra')?.description).toBe('Extra field description');
  });

  it('does not throw when descriptionOverrides has unknown schema key', () => {
    const document = {
      components: {
        schemas: {
          Only: {
            type: 'object',
            properties: { v: { type: 'string', description: 'V' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Only'],
        descriptionOverrides: {
          NonExistent: { v: 'Ignored' },
        },
      },
    });
    expect(result.classes.length).toBe(1);
    expect(result.classes[0].properties?.find((p) => p.name === 'v')?.description).toBe('V');
  });
});
