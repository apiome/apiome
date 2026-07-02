/**
 * Unit tests for #761: Example generation for imported properties.
 * When generateExamples: true, properties without an example get a generated
 * example (by type/format). Existing examples are preserved; $refs are skipped.
 */

import { describe, it, expect } from '@jest/globals';
import { openApiImporter } from '../../lib/importers/openapi';

describe('#761 Generate examples during property import', () => {
  it('does not add examples when generateExamples is false', () => {
    const document = {
      components: {
        schemas: {
          Item: {
            type: 'object',
            properties: {
              name: { type: 'string' },
              count: { type: 'integer' },
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
        generateExamples: false,
      },
    });
    expect(result.classes).toHaveLength(1);
    const nameProp = result.classes[0].properties!.find((p) => p.name === 'name');
    const countProp = result.classes[0].properties!.find((p) => p.name === 'count');
    expect(nameProp?.data.example).toBeUndefined();
    expect(countProp?.data.example).toBeUndefined();
  });

  it('does not add examples when generateExamples is undefined', () => {
    const document = {
      components: {
        schemas: {
          Item: {
            type: 'object',
            properties: { title: { type: 'string' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: {
        selectedSchemas: ['Item'],
        applyNamingConvention: false,
      },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'title')?.data.example).toBeUndefined();
  });

  it('generates example for string property when generateExamples is true', () => {
    const document = {
      components: {
        schemas: {
          Item: {
            type: 'object',
            properties: {
              name: { type: 'string' },
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
        generateExamples: true,
      },
    });
    const nameProp = result.classes[0].properties!.find((p) => p.name === 'name');
    expect(nameProp?.data.example).toBe('example');
  });

  it('generates example for integer property', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: { count: { type: 'integer' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'count')?.data.example).toBe(42);
  });

  it('generates example for number property', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: { value: { type: 'number' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'value')?.data.example).toBe(42.5);
  });

  it('generates example for boolean property', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: { active: { type: 'boolean' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'active')?.data.example).toBe(true);
  });

  it('generates example for string format date', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: { birthDate: { type: 'string', format: 'date' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'birthDate')?.data.example).toBe('2025-02-11');
  });

  it('generates example for string format date-time', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: { createdAt: { type: 'string', format: 'date-time' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'createdAt')?.data.example).toBe('2025-02-11T12:00:00Z');
  });

  it('generates example for string format email', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: { email: { type: 'string', format: 'email' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'email')?.data.example).toBe('user@example.com');
  });

  it('generates example for string format uuid', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: { id: { type: 'string', format: 'uuid' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'id')?.data.example).toBe('123e4567-e89b-12d3-a456-426614174000');
  });

  it('generates example for string format uri', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: { link: { type: 'string', format: 'uri' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'link')?.data.example).toBe('https://example.com');
  });

  it('generates example for enum (first value)', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              status: { type: 'string', enum: ['draft', 'published', 'archived'] },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'status')?.data.example).toBe('draft');
  });

  it('does not override existing example from spec', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              name: { type: 'string', example: 'Custom Example' },
              count: { type: 'integer', example: 100 },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'name')?.data.example).toBe('Custom Example');
    expect(result.classes[0].properties!.find((p) => p.name === 'count')?.data.example).toBe(100);
  });

  it('generates example for array property (empty array)', () => {
    const document = {
      components: {
        schemas: {
          S: {
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
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    const tagsProp = result.classes[0].properties!.find((p) => p.name === 'tags');
    expect(tagsProp?.data.example).toEqual(['example']);
    expect(tagsProp?.data.items?.example).toBe('example');
  });

  it('generates example for array of numbers', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              scores: { type: 'array', items: { type: 'number' } },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    const scoresProp = result.classes[0].properties!.find((p) => p.name === 'scores');
    expect(scoresProp?.data.example).toEqual([42.5]);
  });

  it('generates example for object property (empty object)', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              metadata: { type: 'object' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'metadata')?.data.example).toEqual({});
  });

  it('applies generated examples to nested inline object children', () => {
    const document = {
      components: {
        schemas: {
          Parent: {
            type: 'object',
            properties: {
              child: {
                type: 'object',
                properties: {
                  label: { type: 'string' },
                  amount: { type: 'integer' },
                },
              },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['Parent'], applyNamingConvention: false, generateExamples: true },
    });
    const parent = result.classes[0];
    const childProp = parent.properties!.find((p) => p.name === 'child');
    expect(childProp?.data.example).toEqual({});
    const labelChild = childProp?.children?.find((c) => c.name === 'label');
    const amountChild = childProp?.children?.find((c) => c.name === 'amount');
    expect(labelChild?.data.example).toBe('example');
    expect(amountChild?.data.example).toBe(42);
  });

  it('does not add example to $ref properties (refs are preserved as-is)', () => {
    const document = {
      components: {
        schemas: {
          User: {
            type: 'object',
            properties: {
              id: { type: 'string' },
              profile: { $ref: '#/components/schemas/Profile' },
            },
          },
          Profile: {
            type: 'object',
            properties: { displayName: { type: 'string' } },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['User', 'Profile'], applyNamingConvention: false, generateExamples: true },
    });
    const user = result.classes.find((c) => c.originalSchemaKey === 'User' || c.name === 'User');
    const idProp = user!.properties!.find((p) => p.name === 'id');
    const profileProp = user!.properties!.find((p) => p.name === 'profile');
    expect(idProp?.data.example).toBe('example');
    expect(profileProp?.data.$ref).toBe('#/components/schemas/Profile');
    expect(profileProp?.data.example).toBeUndefined();
  });

  it('works together with defaultValues and descriptionOverrides', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              name: { type: 'string' },
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
        descriptionOverrides: { S: { name: 'Item name' } },
        generateExamples: true,
      },
    });
    const nameProp = result.classes[0].properties!.find((p) => p.name === 'name');
    const countProp = result.classes[0].properties!.find((p) => p.name === 'count');
    expect(nameProp?.data.default).toBe('');
    expect(nameProp?.data.example).toBe('example');
    expect(nameProp?.description).toBe('Item name');
    expect(countProp?.data.default).toBe(0);
    expect(countProp?.data.example).toBe(42);
  });

  it('integer with minimum uses min value for generated example', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              level: { type: 'integer', minimum: 1 },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'level')?.data.example).toBe(1);
  });

  it('plain string without format gets "example" as generated example', () => {
    const document = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: {
              code: { type: 'string' },
            },
          },
        },
      },
    };
    const result = openApiImporter.normalize({
      document,
      options: { selectedSchemas: ['S'], applyNamingConvention: false, generateExamples: true },
    });
    expect(result.classes[0].properties!.find((p) => p.name === 'code')?.data.example).toBe('example');
  });
});
