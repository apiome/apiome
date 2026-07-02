/**
 * Unit tests for reference conflict detection (#584): broken or ambiguous references.
 */
import { detectReferenceConflicts } from '../../src/app/utils/reference-conflict-detection';

describe('detectReferenceConflicts (#584)', () => {
  test('returns empty when no document', () => {
    expect(
      detectReferenceConflicts({ document: null, schemaNames: ['A'] })
    ).toEqual([]);
    expect(
      detectReferenceConflicts({ document: undefined, schemaNames: ['A'] })
    ).toEqual([]);
  });

  test('returns empty when schemaNames is empty', () => {
    const doc = {
      components: {
        schemas: {
          User: { type: 'object', properties: { ref: { $ref: '#/components/schemas/Other' } } },
        },
      },
    };
    expect(detectReferenceConflicts({ document: doc, schemaNames: [] })).toEqual([]);
  });

  test('returns empty when all refs point to existing schemas in document', () => {
    const doc = {
      components: {
        schemas: {
          Order: {
            type: 'object',
            properties: {
              customer: { $ref: '#/components/schemas/Customer' },
              items: { type: 'array', items: { $ref: '#/components/schemas/LineItem' } },
            },
          },
          Customer: { type: 'object', properties: { id: { type: 'string' } } },
          LineItem: { type: 'object', properties: { id: { type: 'string' } } },
        },
      },
    };
    expect(
      detectReferenceConflicts({ document: doc, schemaNames: ['Order', 'Customer', 'LineItem'] })
    ).toEqual([]);
  });

  test('detects broken reference when $ref points to non-existent schema', () => {
    const doc = {
      components: {
        schemas: {
          Order: {
            type: 'object',
            properties: {
              customer: { $ref: '#/components/schemas/Customer' },
              missing: { $ref: '#/components/schemas/NonExistent' },
            },
          },
          Customer: { type: 'object', properties: {} },
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: doc,
      schemaNames: ['Order'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('reference_conflict');
    expect(conflicts[0].schemaName).toBe('Order');
    expect(conflicts[0].message).toContain('non-existent');
    expect(conflicts[0].detail).toContain('NonExistent');
  });

  test('detects broken ref in allOf', () => {
    const doc = {
      components: {
        schemas: {
          Extended: {
            allOf: [
              { $ref: '#/components/schemas/Base' },
              { $ref: '#/components/schemas/MissingMixin' },
            ],
          },
          Base: { type: 'object', properties: {} },
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: doc,
      schemaNames: ['Extended'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('Extended');
    expect(conflicts[0].detail).toContain('MissingMixin');
  });

  test('detects ambiguous external $ref (URL)', () => {
    const doc = {
      components: {
        schemas: {
          Proxy: {
            type: 'object',
            properties: {
              external: { $ref: 'https://example.com/schemas/External.json' },
            },
          },
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: doc,
      schemaNames: ['Proxy'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('reference_conflict');
    expect(conflicts[0].schemaName).toBe('Proxy');
    expect(conflicts[0].message).toContain('external');
    expect(conflicts[0].detail).toContain('https://');
  });

  test('detects ref to schema not selected for import when selectedSchemaNames provided', () => {
    const doc = {
      components: {
        schemas: {
          Order: {
            type: 'object',
            properties: {
              customer: { $ref: '#/components/schemas/Customer' },
              items: { type: 'array', items: { $ref: '#/components/schemas/LineItem' } },
            },
          },
          Customer: { type: 'object', properties: {} },
          LineItem: { type: 'object', properties: {} },
        },
      },
    };
    // Only Order selected; Customer and LineItem exist in doc but are not selected
    const conflicts = detectReferenceConflicts({
      document: doc,
      schemaNames: ['Order'],
      selectedSchemaNames: ['Order'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe('reference_conflict');
    expect(conflicts[0].schemaName).toBe('Order');
    expect(conflicts[0].message).toContain('not selected');
    expect(conflicts[0].detail).toMatch(/Customer|LineItem/);
  });

  test('no "not selected" conflict when all referenced schemas are in selectedSchemaNames', () => {
    const doc = {
      components: {
        schemas: {
          Order: {
            type: 'object',
            properties: {
              customer: { $ref: '#/components/schemas/Customer' },
            },
          },
          Customer: { type: 'object', properties: {} },
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: doc,
      schemaNames: ['Order', 'Customer'],
      selectedSchemaNames: ['Order', 'Customer'],
    });
    expect(conflicts).toEqual([]);
  });

  test('uses definitions (OpenAPI 2) for available schemas', () => {
    const doc = {
      definitions: {
        Order: {
          type: 'object',
          properties: { ref: { $ref: '#/definitions/Customer' } },
        },
        Customer: { type: 'object', properties: {} },
      },
    };
    expect(
      detectReferenceConflicts({ document: doc, schemaNames: ['Order'] })
    ).toEqual([]);

    const docBroken = {
      definitions: {
        Order: {
          type: 'object',
          properties: { ref: { $ref: '#/definitions/Missing' } },
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: docBroken,
      schemaNames: ['Order'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].detail).toContain('Missing');
  });

  test('multiple schemas with broken refs produce one conflict per schema', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'object', properties: { x: { $ref: '#/components/schemas/NoA' } } },
          B: { type: 'object', properties: { y: { $ref: '#/components/schemas/NoB' } } },
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: doc,
      schemaNames: ['A', 'B'],
    });
    expect(conflicts).toHaveLength(2);
    const names = conflicts.map((c) => c.schemaName).sort();
    expect(names).toEqual(['A', 'B']);
    expect(conflicts.find((c) => c.schemaName === 'A')?.detail).toContain('NoA');
    expect(conflicts.find((c) => c.schemaName === 'B')?.detail).toContain('NoB');
  });

  test('impactIfResolved is set for reference_conflict', () => {
    const doc = {
      components: {
        schemas: {
          X: { type: 'object', properties: { r: { $ref: '#/components/schemas/Y' } } },
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: doc,
      schemaNames: ['X'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].impactIfResolved).toBeDefined();
    expect(conflicts[0].impactIfResolved!.length).toBeGreaterThan(0);
  });

  test('each conflict has required ImportConflict shape (kind, schemaName, message)', () => {
    const doc = {
      components: {
        schemas: {
          A: { type: 'object', properties: { x: { $ref: '#/components/schemas/Missing' } } },
        },
      },
    };
    const conflicts = detectReferenceConflicts({ document: doc, schemaNames: ['A'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0]).toMatchObject({
      kind: 'reference_conflict',
      schemaName: 'A',
      message: expect.any(String),
    });
    expect(conflicts[0].message.length).toBeGreaterThan(0);
  });

  test('detects broken ref in oneOf and anyOf', () => {
    const doc = {
      components: {
        schemas: {
          Variant: {
            oneOf: [
              { $ref: '#/components/schemas/TypeA' },
              { $ref: '#/components/schemas/TypeB' },
            ],
          },
          TypeA: { type: 'object', properties: {} },
          // TypeB missing
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: doc,
      schemaNames: ['Variant'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('Variant');
    expect(conflicts[0].detail).toContain('TypeB');
  });

  test('detects broken ref in additionalProperties', () => {
    const doc = {
      components: {
        schemas: {
          MapSchema: {
            type: 'object',
            additionalProperties: { $ref: '#/components/schemas/UnknownValue' },
          },
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: doc,
      schemaNames: ['MapSchema'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('MapSchema');
    expect(conflicts[0].detail).toContain('UnknownValue');
  });

  test('same missing schema referenced multiple times yields one conflict with deduped detail', () => {
    const doc = {
      components: {
        schemas: {
          Multi: {
            type: 'object',
            properties: {
              a: { $ref: '#/components/schemas/Same' },
              b: { $ref: '#/components/schemas/Same' },
              c: { type: 'array', items: { $ref: '#/components/schemas/Same' } },
            },
          },
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: doc,
      schemaNames: ['Multi'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].detail).toContain('Same');
    expect(conflicts[0].detail!.split('Same').length - 1).toBe(1); // "Same" appears once in detail
  });

  test('empty selectedSchemaNames does not report "not selected" conflicts', () => {
    const doc = {
      components: {
        schemas: {
          Order: {
            type: 'object',
            properties: { customer: { $ref: '#/components/schemas/Customer' } },
          },
          Customer: { type: 'object', properties: {} },
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: doc,
      schemaNames: ['Order'],
      selectedSchemaNames: [],
    });
    expect(conflicts).toEqual([]);
  });

  test('detects http external $ref as ambiguous', () => {
    const doc = {
      components: {
        schemas: {
          S: {
            type: 'object',
            properties: { ext: { $ref: 'http://example.com/schema.json' } },
          },
        },
      },
    };
    const conflicts = detectReferenceConflicts({ document: doc, schemaNames: ['S'] });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].message).toContain('external');
    expect(conflicts[0].detail).toContain('http://');
  });

  test('schema with no refs produces no conflicts', () => {
    const doc = {
      components: {
        schemas: {
          Plain: { type: 'object', properties: { id: { type: 'string' } } },
        },
      },
    };
    expect(
      detectReferenceConflicts({ document: doc, schemaNames: ['Plain'] })
    ).toEqual([]);
  });

  test('only considers schemas in schemaNames', () => {
    const doc = {
      components: {
        schemas: {
          Considered: { type: 'object', properties: { ref: { $ref: '#/components/schemas/Other' } } },
          Other: { type: 'object', properties: {} },
        },
      },
    };
    // Only scan Considered; Other exists so ref is valid
    expect(
      detectReferenceConflicts({ document: doc, schemaNames: ['Considered'] })
    ).toEqual([]);
    // If we did not limit to schemaNames we would still get none. So add case where Considered has broken ref
    const doc2 = {
      components: {
        schemas: {
          Considered: { type: 'object', properties: { ref: { $ref: '#/components/schemas/Missing' } } },
          Unconsidered: { type: 'object', properties: { ref: { $ref: '#/components/schemas/Ghost' } } },
        },
      },
    };
    const conflicts = detectReferenceConflicts({
      document: doc2,
      schemaNames: ['Considered'],
    });
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].schemaName).toBe('Considered');
    expect(conflicts[0].detail).toContain('Missing');
  });
});
