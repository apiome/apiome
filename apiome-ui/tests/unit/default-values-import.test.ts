/**
 * Unit tests for #758: Default value assignment during import.
 * - defaultValues in NormalizeOptions: key = external type key, value = default to set.
 * - Applied only when property has no existing default; refs are skipped.
 * - Recurses into children and array items.
 */

import { describe, it, expect } from '@jest/globals';
import { openApiImporter } from '../../lib/importers/openapi';

describe('#758 Default values during import', () => {
  it('sets default for properties that have no default', () => {
    const document = {
      components: {
        schemas: {
          Item: {
            type: 'object',
            properties: {
              name: { type: 'string' },
              count: { type: 'integer' },
              active: { type: 'boolean' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Item'],
        applyNamingConvention: false,
        defaultValues: {
          string: '',
          integer: 0,
          boolean: false,
        },
      },
    });
    expect(result.classes).toHaveLength(1);
    const props = result.classes[0].properties!;
    expect(props.find((p) => p.name === 'name')?.data.default).toBe('');
    expect(props.find((p) => p.name === 'count')?.data.default).toBe(0);
    expect(props.find((p) => p.name === 'active')?.data.default).toBe(false);
  });

  it('does not override existing default from spec', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              name: { type: 'string', default: 'unknown' },
              count: { type: 'integer' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['S'],
        applyNamingConvention: false,
        defaultValues: { string: '', integer: 0 },
      },
    });
    const nameProp = result.classes[0].properties!.find((p) => p.name === 'name');
    const countProp = result.classes[0].properties!.find((p) => p.name === 'count');
    expect(nameProp?.data.default).toBe('unknown');
    expect(countProp?.data.default).toBe(0);
  });

  it('does not set default when key not in defaultValues', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              x: { type: 'number' },
              y: { type: 'string' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['S'],
        applyNamingConvention: false,
        defaultValues: { string: '' },
      },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'x')?.data.default).toBeUndefined();
    expect(result.classes[0].properties!.find((p) => p.name === 'y')?.data.default).toBe('');
  });

  it('applies default to nested inline object children', () => {
    const document = {
      components: {
        schemas: {
          Parent: {
            type: 'object',
            properties: {
              child: {
                type: 'object',
                properties: {
                  value: { type: 'string' },
                },
              },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Parent'],
        applyNamingConvention: false,
        defaultValues: { string: '' },
      },
    });
    const childProp = result.classes[0].properties!.find((p) => p.name === 'child');
    const valueProp = childProp?.children!.find((p) => p.name === 'value');
    expect(valueProp?.data.default).toBe('');
  });

  it('applies default to array items when items have no default', () => {
    const document = {
      components: {
        schemas: {
          Doc: {
            type: 'object',
            properties: {
              ids: { type: 'array', items: { type: 'integer' } },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Doc'],
        applyNamingConvention: false,
        defaultValues: { integer: 0 },
      },
    });
    const idsProp = result.classes[0].properties!.find((p) => p.name === 'ids');
    expect(idsProp?.data.items?.default).toBe(0);
  });

  it('does not modify $ref properties', () => {
    const document = {
      components: {
        schemas: {
          Order: {
            type: 'object',
            properties: {
              id: { type: 'integer' },
              customer: { $ref: '#/components/schemas/Customer' },
            },
          },
          Customer: {
            type: 'object',
            properties: { name: { type: 'string' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Order', 'Customer'],
        applyNamingConvention: false,
        defaultValues: { integer: 0, string: '' },
      },
    });
    const orderClass = result.classes.find((c) => c.name === 'Order')!;
    const customerProp = orderClass.properties!.find((p) => p.name === 'customer');
    expect(customerProp?.data).toEqual({ $ref: '#/components/schemas/Customer' });
    const customerClass = result.classes.find((c) => c.name === 'Customer')!;
    expect(customerClass.properties!.find((p) => p.name === 'name')?.data.default).toBe('');
  });

  it('produces same classes when defaultValues is undefined or empty', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: { x: { type: 'string' } },
          },
        },
      },
    };
    const resultNone = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false },
    });
    const resultEmpty = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, defaultValues: {} },
    });
    expect(resultNone.classes[0].properties![0].data).toEqual(resultEmpty.classes[0].properties![0].data);
    expect(resultNone.classes[0].properties![0].data.default).toBeUndefined();
  });

  it('applies defaultValues after typeMapping (keys are post-mapping type keys)', () => {
    const document = {
      components: {
        schemas: {
          Event: {
            type: 'object',
            properties: {
              at: { type: 'string', format: 'date-time' },
            },
          },
        },
      },
    };
    // After type mapping, at becomes string:date; defaultValues key must match post-mapping key
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Event'],
        applyNamingConvention: false,
        typeMapping: { 'string:date-time': { type: 'string', format: 'date' } },
        defaultValues: { 'string:date': '1970-01-01' },
      },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'at')?.data.default).toBe('1970-01-01');
  });

  it('applies default for type:format keys (string:uuid, integer:int32)', () => {
    const document = {
      components: {
        schemas: {
          Entity: {
            type: 'object',
            properties: {
              id: { type: 'string', format: 'uuid' },
              code: { type: 'integer', format: 'int32' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Entity'],
        applyNamingConvention: false,
        defaultValues: {
          'string:uuid': '00000000-0000-0000-0000-000000000000',
          'integer:int32': 0,
        },
      },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'id')?.data.default).toBe(
      '00000000-0000-0000-0000-000000000000'
    );
    expect(result.classes[0].properties!.find((p) => p.name === 'code')?.data.default).toBe(0);
  });

  it('allows null as default value', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              optional: { type: 'string' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['S'],
        applyNamingConvention: false,
        defaultValues: { string: null },
      },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'optional')?.data.default).toBeNull();
  });

  it('allows object and array as default value', () => {
    const document = {
      components: {
        schemas: {
          Config: {
            type: 'object',
            properties: {
              tags: { type: 'array', items: { type: 'string' } },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Config'],
        applyNamingConvention: false,
        defaultValues: { array: [] },
      },
    });
    const tagsProp = result.classes[0].properties!.find((p) => p.name === 'tags');
    expect(tagsProp?.data.default).toEqual([]);
  });

  it('does not override existing default on array items', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              nums: { type: 'array', items: { type: 'integer', default: 42 } },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['S'],
        applyNamingConvention: false,
        defaultValues: { integer: 0 },
      },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'nums')?.data.items?.default).toBe(42);
  });

  it('applies defaults across multiple classes', () => {
    const document = {
      components: {
        schemas: {
          A: {
            type: 'object',
            properties: { name: { type: 'string' } },
          },
          B: {
            type: 'object',
            properties: { title: { type: 'string' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['A', 'B'],
        applyNamingConvention: false,
        defaultValues: { string: '' },
      },
    });
    expect(result.classes.find((c) => c.name === 'A')!.properties!.find((p) => p.name === 'name')?.data.default).toBe(
      ''
    );
    expect(result.classes.find((c) => c.name === 'B')!.properties!.find((p) => p.name === 'title')?.data.default).toBe(
      ''
    );
  });

  it('applies defaults when naming convention is enabled', () => {
    const document = {
      components: {
        schemas: {
          user_profile: {
            type: 'object',
            properties: {
              first_name: { type: 'string' },
              score: { type: 'integer' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['user_profile'],
        applyNamingConvention: true,
        classNamingConvention: 'PascalCase',
        propertyNamingConvention: 'camelCase',
        defaultValues: { string: '', integer: 0 },
      },
    });
    expect(result.classes[0].name).toBe('UserProfile');
    const firstName = result.classes[0].properties!.find((p) => p.name === 'firstName');
    const score = result.classes[0].properties!.find((p) => p.name === 'score');
    expect(firstName?.data.default).toBe('');
    expect(score?.data.default).toBe(0);
  });

  it('applies default to array items when items have scalar type (e.g. number:double)', () => {
    const document = {
      components: {
        schemas: {
          List: {
            type: 'object',
            properties: {
              values: {
                type: 'array',
                items: { type: 'number', format: 'double' },
              },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['List'],
        applyNamingConvention: false,
        defaultValues: { 'number:double': 0.0 },
      },
    });
    const valuesProp = result.classes[0].properties!.find((p) => p.name === 'values');
    expect(valuesProp?.data.items?.default).toBe(0.0);
  });
});
